// Read-only Series-7 bitstream CRC checker. Does not program hardware.
// Register/data recurrence is cross-checked against Project X-Ray's crc.h
// and its four upstream known-answer tests. Register sequencing follows UG470.
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

static uint32_t extend(uint32_t state, uint32_t reg, uint32_t value) {
    uint64_t input = uint64_t(value) | (uint64_t(reg & 31) << 32);
    for (int bit = 0; bit != 37; ++bit) {
        bool feedback = (state ^ input) & 1;
        state >>= 1;
        if (feedback) state ^= 0x82f63b78;
        input >>= 1;
    }
    return state;
}

static void require(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}

int main(int argc, char **argv) {
    try {
        require(extend(0, 0, 0) == 0 && extend(0, 16, 0) == 0x82f63b78
                && extend(0, ~uint32_t(0), ~uint32_t(0)) == 0xbf86d4df
                && extend(~uint32_t(0), 0, 0) == 0xc631e365,
                "Project X-Ray known-answer vector mismatch");
        require(argc == 2, "Usage: openxc7_bitstream_crc input.bit");
        std::ifstream file(argv[1], std::ios::binary);
        require(bool(file), "Cannot open bitstream");
        std::vector<uint8_t> data((std::istreambuf_iterator<char>(file)), {});
        auto u16 = [&](size_t p) -> uint32_t {
            require(p + 2 <= data.size(), "Truncated 16-bit field");
            return (uint32_t(data[p]) << 8) | data[p + 1];
        };
        auto u32 = [&](size_t p) -> uint32_t {
            require(p + 4 <= data.size(), "Truncated 32-bit field");
            return (uint32_t(data[p]) << 24) | (uint32_t(data[p + 1]) << 16)
                   | (uint32_t(data[p + 2]) << 8) | data[p + 3];
        };
        size_t cursor = 2, signature_size = u16(0);
        std::vector<uint8_t> signature{0x0f,0xf0,0x0f,0xf0,0x0f,0xf0,0x0f,0xf0,0};
        require(signature_size == signature.size() && data.size() >= cursor + signature_size,
                "Wrong bitstream header signature size");
        require(std::vector<uint8_t>(data.begin()+cursor, data.begin()+cursor+signature_size) == signature,
                "Wrong bitstream header signature");
        cursor += signature_size;
        require(u16(cursor) == 1, "Wrong bitstream header marker");
        cursor += 2;
        unsigned seen = 0;
        size_t payload = 0, size = 0;
        for (;;) {
            require(cursor < data.size(), "Missing bitstream header field");
            char tag = data[cursor++];
            if (tag == 'e') { size = u32(cursor); payload = cursor + 4; break; }
            require(tag >= 'a' && tag <= 'd', "Unexpected bitstream header field");
            unsigned flag = 1u << (tag - 'a');
            require(!(seen & flag), "Duplicate bitstream header field");
            seen |= flag;
            size_t n = u16(cursor); cursor += 2;
            require(cursor + n <= data.size(), "Truncated bitstream header value");
            if (tag == 'b') {
                std::string part(data.begin()+cursor, data.begin()+cursor+n);
                if (!part.empty() && part.back() == '\0') part.pop_back();
                require(part == "xc7k480tffg1156-2" || part == "7k480tffg1156", "Wrong FPGA part");
            }
            cursor += n;
        }
        require(seen == 15 && payload + size == data.size() && size % 4 == 0,
                "Bitstream payload bounds or fields disagree");
        cursor = payload;
        while (cursor < payload + 128 && cursor + 4 <= data.size() && u32(cursor) != 0xaa995566)
            cursor += 4;
        require(cursor < payload + 128 && u32(cursor) == 0xaa995566, "Missing aligned synchronization word");
        cursor += 4;
        uint32_t state = 0, reg = 0;
        bool have_reg = false;
        unsigned checks = 0, ids = 0, starts = 0, desyncs = 0;
        uint64_t fdri = 0, window_fdri = 0, write_words = 0;
        struct Reset { size_t header, value; uint32_t crc; uint64_t words; };
        std::vector<Reset> resets;
        std::vector<std::pair<size_t, uint32_t>> checkpoints;
        while (cursor < data.size()) {
            size_t header = cursor;
            uint32_t word = u32(cursor); cursor += 4;
            if (word == 0 || word == 0xffffffff) continue;
            unsigned kind = word >> 29, op = (word >> 27) & 3;
            require((kind == 1 || kind == 2) && op <= 2, "Unsupported configuration packet");
            size_t count;
            if (kind == 1) { reg = (word >> 13) & 0x3fff; have_reg = true; count = word & 0x7ff; }
            else { require(have_reg, "Type-2 packet without register context"); count = word & 0x7ffffff; }
            require(cursor + 4 * count <= data.size() && reg <= 31, "Packet extent or register unsupported");
            require(op != 1 && (op != 0 || count == 0), "Read or data-bearing NOP unsupported");
            if (op == 2) {
                require(reg != 8, "LOUT CRC semantics not qualified by the selected reference images");
                for (size_t i = 0; i < count; ++i) {
                    uint32_t value = u32(cursor + 4 * i);
                    ++write_words;
                    if (reg == 12) { require(value == 0x03751093, "Wrong configuration IDCODE"); ++ids; }
                    if (reg == 2) { ++fdri; ++window_fdri; }
                    if (reg == 4 && (value & 31) == 5) ++starts;
                    if (reg == 4 && (value & 31) == 13) ++desyncs;
                    if (reg == 4 && (value & 31) == 7) {
                        require(count == 1, "Unsupported multiword CRC-reset command");
                        resets.push_back({header, cursor, state, window_fdri});
                        state = 0; window_fdri = 0;
                    } else if (reg == 0) {
                        require(count == 1, "Unsupported multiword CRC checkpoint");
                        if (value != state) {
                            std::cout << "{\"status\":\"CRC_MISMATCH\",\"file_offset\":" << cursor
                                      << ",\"stored\":" << value << ",\"computed\":" << state << "}\n";
                            return 1;
                        }
                        checkpoints.emplace_back(cursor, value); ++checks;
                        state = 0; window_fdri = 0;
                    } else state = extend(state, reg, value);
                }
            }
            cursor += 4 * count;
        }
        require(ids == 1 && fdri > 100000 && starts == 1 && desyncs == 1,
                "Incomplete full-device configuration sequence");
        std::cout << "{\"status\":\"" << (checks ? "ALL_PRESENT_CRC_CHECKPOINTS_MATCH" : "NO_CRC_CHECKPOINTS_RESET_ONLY")
                  << "\",\"crc_checkpoints\":" << checks << ",\"fdri_words\":" << fdri
                  << ",\"register_data_words\":" << write_words << ",\"known_answer_vectors\":4,\"resets\":[";
        for (size_t i = 0; i < resets.size(); ++i) {
            if (i) std::cout << ',';
            auto r = resets[i];
            std::cout << "{\"header_file_offset\":" << r.header << ",\"value_file_offset\":" << r.value
                      << ",\"computed_crc_before_reset\":" << r.crc << ",\"fdri_words_since_reset\":" << r.words << '}';
        }
        std::cout << "],\"checkpoints\":[";
        for (size_t i = 0; i < checkpoints.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << "{\"value_file_offset\":" << checkpoints[i].first << ",\"crc\":" << checkpoints[i].second << '}';
        }
        std::cout << "]}\n";
        return checks ? 0 : 2;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
