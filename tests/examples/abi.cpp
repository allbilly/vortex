#include <cstddef>
#include <cstdio>
#include <vortex2.h>
#include "common.h"

#define FIELD(type, field) std::printf(" %zu", offsetof(type, field))

int main() {
  std::printf("KernelArgs %zu", sizeof(kernel_args));
  FIELD(kernel_args, a); FIELD(kernel_args, b); FIELD(kernel_args, c);
  FIELD(kernel_args, count); FIELD(kernel_args, op); FIELD(kernel_args, dims);
  std::puts("");
  std::printf("QueueInfo %zu", sizeof(vx_queue_info_t));
  FIELD(vx_queue_info_t, struct_size); FIELD(vx_queue_info_t, next);
  FIELD(vx_queue_info_t, priority); FIELD(vx_queue_info_t, flags);
  std::puts("");
  std::printf("LaunchInfo %zu", sizeof(vx_launch_info_t));
  FIELD(vx_launch_info_t, struct_size); FIELD(vx_launch_info_t, next);
  FIELD(vx_launch_info_t, kernel); FIELD(vx_launch_info_t, args_host);
  FIELD(vx_launch_info_t, args_size); FIELD(vx_launch_info_t, ndim);
  FIELD(vx_launch_info_t, grid_dim); FIELD(vx_launch_info_t, block_dim);
  FIELD(vx_launch_info_t, lmem_size); FIELD(vx_launch_info_t, cluster_dim);
  std::puts("");
}
