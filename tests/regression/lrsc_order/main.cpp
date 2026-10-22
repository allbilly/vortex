#include <vortex2.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <vector>
#include "common.h"

static vx_device_h device;
static vx_queue_h queue;
static vx_buffer_h memory, results;
static vx_module_h module;
static vx_kernel_h kernel;

void cleanup() {
  if (kernel) vx_kernel_release(kernel);
  if (module) vx_module_release(module);
  if (memory) vx_buffer_release(memory);
  if (results) vx_buffer_release(results);
  if (queue) vx_queue_release(queue);
  if (device) {
    vx_device_dump_perf(device, stdout);
    vx_device_release(device);
  }
}

static void check(vx_result_t result, const char* expression) {
  if (result == VX_SUCCESS) return;
  std::fprintf(stderr, "%s: %s\n", expression, vx_result_string(result));
  cleanup();
  std::exit(1);
}

#define RT_CHECK(expression) check((expression), #expression)

int main(int argc, char** argv) {
  uint32_t iterations = 4;
  uint32_t wait_seconds = 60;
  bool single = false;
  bool cas_only = false;
  int option;
  while ((option = getopt(argc, argv, "n:w:sch")) != -1) {
    if (option == 's') single = true;
    else if (option == 'c') cas_only = true;
    else if (option == 'n' || option == 'w') {
      char* end = nullptr;
      const auto value = std::strtoul(optarg, &end, 10);
      if (!end || *end || value == 0 || value > (option == 'n' ? 128ul : 3600ul)) return 2;
      if (option == 'n') iterations = uint32_t(value);
      else wait_seconds = uint32_t(value);
    } else {
      std::puts("Usage: lrsc_order [-n1..128] [-w1..3600: host wait seconds] [-s: one active hart] [-c: native CAS only]");
      return option == 'h' ? 0 : 2;
    }
  }
#if !VX_CFG_EXT_ZACAS_ENABLED
  if (cas_only) {
    std::fprintf(stderr, "CAS-only mode requires Zacas\n");
    return 2;
  }
#endif
  RT_CHECK(vx_device_open(0, &device));
  uint64_t cores, warps, threads, local_size;
  RT_CHECK(vx_device_query(device, VX_CAPS_NUM_CORES, &cores));
  RT_CHECK(vx_device_query(device, VX_CAPS_NUM_WARPS, &warps));
  RT_CHECK(vx_device_query(device, VX_CAPS_NUM_THREADS, &threads));
  RT_CHECK(vx_device_query(device, VX_CAPS_LOCAL_MEM_SIZE, &local_size));
  const uint32_t block = single ? 1 : uint32_t(warps * threads);
  const uint32_t harts = single ? 1 : uint32_t(cores * block);
  if (uint64_t(block) * LRSC_LOCAL_STRIDE > local_size) {
    std::fprintf(stderr, "Requested CTA exceeds local-memory capacity\n");
    cleanup();
    return 2;
  }
  kernel_arg_t args = {0, 0, harts, iterations, uint32_t(cas_only)};
  vx_queue_info_t info = {sizeof(info), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0};
  RT_CHECK(vx_queue_create(device, &info, &queue));
  RT_CHECK(vx_buffer_create(device, uint64_t(harts) * LRSC_GLOBAL_STRIDE, VX_MEM_READ_WRITE, &memory));
  RT_CHECK(vx_buffer_address(memory, &args.global_addr));
  RT_CHECK(vx_buffer_create(device, uint64_t(harts) * sizeof(result_t), VX_MEM_READ_WRITE, &results));
  RT_CHECK(vx_buffer_address(results, &args.result_addr));
  std::vector<result_t> output(harts);
  std::memset(output.data(), 0xa5, output.size() * sizeof(result_t));
  RT_CHECK(vx_enqueue_write(queue, results, 0, output.data(), output.size() * sizeof(result_t), 0, nullptr, nullptr));
  RT_CHECK(vx_module_load_file(device, "kernel.vxbin", &module));
  RT_CHECK(vx_module_get_kernel(module, "main", &kernel));
  vx_launch_info_t launch = {};
  launch.struct_size = sizeof(launch);
  launch.kernel = kernel;
  launch.args_host = &args;
  launch.args_size = sizeof(args);
  launch.ndim = 1;
  launch.grid_dim[0] = single ? 1 : uint32_t(cores);
  launch.block_dim[0] = block;
  launch.lmem_size = block * LRSC_LOCAL_STRIDE;
  vx_event_h launched, read;
  RT_CHECK(vx_enqueue_launch(queue, &launch, 0, nullptr, &launched));
  RT_CHECK(vx_enqueue_read(queue, output.data(), results, 0, output.size() * sizeof(result_t), 1, &launched, &read));
  RT_CHECK(vx_event_wait_value(read, 1, uint64_t(wait_seconds) * 1000000000ull));
  vx_event_release(read);
  vx_event_release(launched);
  uint32_t errors = 0, observed_failed_sc = 0;
  for (uint32_t hart = 0; hart < harts; ++hart) {
    const auto& result = output[hart];
    observed_failed_sc |= result.first_sc_failed;
    bool failed = result.forbidden_success || result.failed_sc_write;
    if (!cas_only) failed |= result.seen != case_mask()
        || result.global_progress != iterations || result.local_progress != iterations
        || result.global_attempts < iterations || result.local_attempts < iterations;
#if VX_CFG_EXT_ZACAS_ENABLED
    failed |= result.cas_seen != 3 || result.cas_errors != 0;
#endif
    if (failed) {
      std::fprintf(stderr, "FAIL task%u hart%u: seen=%04x forbidden_success=%04x failed_sc_write=%04x "
                   "progress=%u/%u attempts=%u/%u cas_seen=%x cas_errors=%x\n", hart, result.hart, result.seen,
                   result.forbidden_success, result.failed_sc_write, result.global_progress,
                   result.local_progress, result.global_attempts, result.local_attempts,
                   result.cas_seen, result.cas_errors);
      ++errors;
    }
  }
  const uint32_t required_failed_sc = case_mask() & 0xfcu;
  if (!cas_only && (observed_failed_sc & required_failed_sc) != required_failed_sc) {
    std::fprintf(stderr, "FAIL: missing intervening failed-SC coverage: seen=%x required=%x\n",
                 observed_failed_sc, required_failed_sc);
    ++errors;
  }
  std::printf("LRSC order: harts=%u iterations=%u enabled_cases=%04x failed_first_sc=%04x cas_only=%u "
              "global_banks=%u local_banks=%u lsu_lanes=%u simd_width=%u\n", harts,
              iterations, cas_only ? 0 : case_mask(), observed_failed_sc, unsigned(cas_only), unsigned(LRSC_GLOBAL_BANKS),
              unsigned(VX_CFG_LMEM_NUM_BANKS), unsigned(VX_CFG_NUM_LSU_LANES), unsigned(VX_CFG_SIMD_WIDTH));
  cleanup();
  if (errors) return 1;
  std::puts("PASSED: LRSC ordering/bounded progress and enabled native mixed-local/global nonzero CAS checks");
  return 0;
}
