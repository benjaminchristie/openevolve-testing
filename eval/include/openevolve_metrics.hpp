// Standard reporting contract for projects evaluated by eval/harness.py:
// one line of JSON on stdout, {"status": "ok"|"error", "metrics": {...}}.
// Handles JSON-building and exception-safety so each project doesn't have to
// re-derive it (and re-risk the escaping bugs that motivated this header).
//
// Available without an include-path hassle -- harness.py puts this directory
// on CPATH automatically. Usage:
//
//     #include <openevolve_metrics.hpp>
//     using namespace openevolve;
//
//     void solve() { ... }  // the @evolve-tagged code
//
//     int main() {
//         return guarded([]() {
//             Timer t;
//             solve();
//             bool correct = check();
//             report(correct, Metrics().add("duration_ms", t.elapsed_ms()),
//                    correct ? "" : "result did not match expected value");
//             return correct ? 0 : 1;
//         });
//     }
#pragma once

#include <chrono>
#include <exception>
#include <iostream>
#include <sstream>
#include <string>

namespace openevolve {

class Timer {
public:
    Timer() : start_(std::chrono::high_resolution_clock::now()) {}

    double elapsed_ms() const {
        auto end = std::chrono::high_resolution_clock::now();
        return std::chrono::duration<double, std::milli>(end - start_).count();
    }

private:
    std::chrono::high_resolution_clock::time_point start_;
};

inline std::string escape_json(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) {
        if (c == '"' || c == '\\') out += '\\';
        if (c == '\n') { out += "\\n"; continue; }
        out += c;
    }
    return out;
}

// ordered metrics builder so callers don't hand-write "<<" chains
class Metrics {
public:
    Metrics& add(const std::string& name, double value) {
        if (!first_) oss_ << ", ";
        oss_ << "\"" << escape_json(name) << "\": " << value;
        first_ = false;
        return *this;
    }

    std::string json() const { return oss_.str(); }

private:
    std::ostringstream oss_;
    bool first_ = true;
};

inline void report(bool ok, const Metrics& metrics, const std::string& message = "") {
    std::cout << "{\"status\": \"" << (ok ? "ok" : "error") << "\""
               << ", \"metrics\": {" << metrics.json() << "}";
    if (!message.empty()) {
        std::cout << ", \"message\": \"" << escape_json(message) << "\"";
    }
    std::cout << "}" << std::endl;
}

// Runs fn(); an exception becomes a clean status="error" report instead of a
// crash with no stdout. Returns fn()'s return code, or 1 on a caught exception.
template <typename Fn>
int guarded(Fn&& fn) {
    try {
        return fn();
    } catch (const std::exception& e) {
        report(false, Metrics{}, std::string("unhandled exception: ") + e.what());
        return 1;
    } catch (...) {
        report(false, Metrics{}, "unhandled non-std::exception");
        return 1;
    }
}

}  // namespace openevolve
