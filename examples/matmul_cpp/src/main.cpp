#include <chrono>
#include <cmath>
#include <iostream>
#include <vector>

/**
@evolve
*/
void matrix_multiply(const std::vector<double>& A, const std::vector<double>& B, std::vector<double>& C, int N) {
    for (int i = 0; i < N; ++i) {
        for (int j = 0; j < N; ++j) {
            double sum = 0.0;
            for (int k = 0; k < N; ++k) {
                sum += A[i * N + k] * B[k * N + j];
            }
            C[i * N + j] = sum;
        }
    }
}

int main() {
    const int N = 512;
    std::vector<double> A(N * N, 1.0);
    std::vector<double> B(N * N, 2.0);
    std::vector<double> C(N * N, 0.0);

    auto start = std::chrono::high_resolution_clock::now();
    matrix_multiply(A, B, C, N);
    auto end = std::chrono::high_resolution_clock::now();
    double duration_ms = std::chrono::duration<double, std::milli>(end - start).count();

    double expected = static_cast<double>(N) * 1.0 * 2.0;
    bool correct = true;
    for (int i = 0; i < N && correct; ++i) {
        for (int j = 0; j < N; ++j) {
            if (std::fabs(C[i * N + j] - expected) > 1e-3) {
                correct = false;
                break;
            }
        }
    }

    // Evaluators generally parse this JSON line rather than eyeballing text output,
    // since a structured contract is what lets a single generic harness score any
    // project without a bespoke per-project stdout parser.
    std::cout << "{\"status\": \"" << (correct ? "ok" : "error")
               << "\", \"metrics\": {\"duration_ms\": " << duration_ms << "}"
               << (correct ? "" : ", \"message\": \"result did not match expected value\"")
               << "}" << std::endl;
    return correct ? 0 : 1;
}
