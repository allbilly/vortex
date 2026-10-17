#include <vortex2.h>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

static void check(vx_result_t result, const char* operation) {
    if (result != VX_SUCCESS) {
        std::fprintf(stderr, "%s: %s\n", operation, vx_result_string(result));
        std::exit(1);
    }
}

static void verify(vx_queue_h queue, vx_buffer_h buffer,
                   const std::vector<uint8_t>& expected) {
    std::vector<uint8_t> actual(expected.size());
    vx_event_h event = nullptr;
    check(vx_enqueue_read(queue, actual.data(), buffer, 0, actual.size(),
                          0, nullptr, &event), "read");
    check(vx_event_wait_value(event, 1, VX_TIMEOUT_INFINITE), "wait");
    check(vx_event_release(event), "release event");
    for (size_t byte = 0; byte < actual.size(); ++byte) {
        if (actual[byte] != expected[byte]) {
            std::fprintf(stderr, "Byte %zu: expected %u, read %u\n",
                         byte, unsigned(expected[byte]), unsigned(actual[byte]));
            std::exit(1);
        }
    }
}

int main() {
    vx_device_h device = nullptr;
    check(vx_device_open(0, &device), "open");
    uint64_t clock_rate = 0;
    check(vx_device_query(device, VX_CAPS_CLOCK_RATE, &clock_rate), "clock rate");
    if (clock_rate != VX_CFG_PLATFORM_CLOCK_RATE) {
        std::fprintf(stderr, "Runtime clock %llu MHz differs from build configuration %u MHz\n",
                     static_cast<unsigned long long>(clock_rate), unsigned(VX_CFG_PLATFORM_CLOCK_RATE));
        check(vx_device_release(device), "release device");
        return 1;
    }
    uint64_t memory_bandwidth = 0;
    check(vx_device_query(device, VX_CAPS_PEAK_MEM_BW, &memory_bandwidth), "memory bandwidth");
    if (memory_bandwidth != VX_CFG_PLATFORM_MEMORY_PEAK_BW) {
        std::fprintf(stderr, "Runtime bandwidth %llu MB/s differs from build configuration %u MB/s\n",
                     static_cast<unsigned long long>(memory_bandwidth), unsigned(VX_CFG_PLATFORM_MEMORY_PEAK_BW));
        check(vx_device_release(device), "release device");
        return 1;
    }
    std::printf("Runtime capabilities: %llu MHz, peak memory %llu MB/s\n",
                static_cast<unsigned long long>(clock_rate), static_cast<unsigned long long>(memory_bandwidth));
    vx_queue_info_t info = {sizeof(info), nullptr, VX_QUEUE_PRIORITY_NORMAL, 0};
    vx_queue_h queue = nullptr;
    check(vx_queue_create(device, &info, &queue), "create queue");

    constexpr std::array<uint64_t, 4> addresses = {
        0x00100000, 0x40100000, 0x7fffd000, 0x7ffee000
    };
    std::array<vx_buffer_h, addresses.size()> buffers{};
    std::array<std::vector<uint8_t>, addresses.size()> reference;
    for (size_t region = 0; region < addresses.size(); ++region) {
        reference[region].resize(8192);
        for (size_t byte = 0; byte < reference[region].size(); ++byte) {
            reference[region][byte] = uint8_t(region * 53 + byte * 17 + byte / 64);
        }
        check(vx_buffer_reserve(device, addresses[region], reference[region].size(),
                               VX_MEM_READ | VX_MEM_WRITE, &buffers[region]), "reserve");
        uint64_t address = 0;
        check(vx_buffer_address(buffers[region], &address), "buffer address");
        if (address != addresses[region]) {
            std::fprintf(stderr, "Reserved address changed\n");
            return 1;
        }
        check(vx_enqueue_write(queue, buffers[region], 0, reference[region].data(),
                               reference[region].size(), 0, nullptr, nullptr), "write");
    }
    for (size_t region = 0; region < addresses.size(); ++region) {
        verify(queue, buffers[region], reference[region]);
        std::printf("Verified 8192 bytes at 0x%08llx\n",
                    static_cast<unsigned long long>(addresses[region]));
    }

    const std::array<uint8_t, 13> patch = {0x91, 0x27, 0xf4, 0x63, 0x08, 0xbb,
        0x51, 0x3c, 0xae, 0x79, 0x12, 0xe0, 0x45};
    check(vx_enqueue_write(queue, buffers[2], 4093, patch.data(), patch.size(),
                           0, nullptr, nullptr), "partial boundary write");
    for (size_t byte = 0; byte < patch.size(); ++byte) {
        reference[2][4093 + byte] = patch[byte];
    }
    std::array<uint8_t, 32> partial_read;
    partial_read.fill(0xa5);
    vx_event_h event = nullptr;
    check(vx_enqueue_read(queue, partial_read.data() + 3, buffers[2], 4093,
                          patch.size(), 0, nullptr, &event), "partial boundary read");
    check(vx_event_wait_value(event, 1, VX_TIMEOUT_INFINITE), "wait partial read");
    check(vx_event_release(event), "release partial read");
    for (size_t byte = 0; byte < partial_read.size(); ++byte) {
        const uint8_t expected = byte >= 3 && byte < 3 + patch.size()
                               ? patch[byte - 3] : 0xa5;
        if (partial_read[byte] != expected) {
            std::fprintf(stderr, "Partial read byte %zu differs\n", byte);
            return 1;
        }
    }
    check(vx_enqueue_copy(queue, buffers[3], 77, buffers[2], 4093, patch.size(),
                          0, nullptr, nullptr), "partial device copy");
    for (size_t byte = 0; byte < patch.size(); ++byte) {
        reference[3][77 + byte] = patch[byte];
    }
    for (size_t region = 0; region < addresses.size(); ++region) {
        verify(queue, buffers[region], reference[region]);
        check(vx_buffer_release(buffers[region]), "release buffer");
    }
    check(vx_queue_release(queue), "release queue");
    check(vx_device_release(device), "release device");
    std::puts("PASSED: CP DMA, 4 distinct regions, CH1 2 GiB bounds, byte-exact upload/download/copy and no aliases");
    return 0;
}
