#include "common.hpp"
#include <openevolve_metrics.hpp>
#include <cmath>
#include <random>
#include <vector>
using namespace openevolve;

namespace {

// Independent reference used only to check matmul's output -- never called
// on the benchmark path, so evolving matmul can't cheat by weakening this.
void reference_matmul(const double* A, const double* B, double* C, int n) {
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            double sum = 0.0;
            for (int k = 0; k < n; ++k) sum += A[i * n + k] * B[k * n + j];
            C[i * n + j] = sum;
        }
    }
}

}  // namespace

int main() {
    return guarded([]() {
        std::mt19937 rng(42);
        std::uniform_real_distribution<double> real_dist(-1.0, 1.0);
        std::uniform_int_distribution<int> int_dist(0, 1'000'000);

        bool correct = true;
        std::string failure;

        // --- linalg: matmul + transpose + vector_norm ---
        const int N = 128;
        std::vector<double> A(N * N), B(N * N), C(N * N), T(N * N), Ref(N * N);
        for (auto& x : A) x = real_dist(rng);
        for (auto& x : B) x = real_dist(rng);

        Timer linalg_timer;
        matmul(A.data(), B.data(), C.data(), N);
        transpose(A.data(), T.data(), N);
        double triangle[3] = {3.0, 4.0, 0.0};
        double norm = vector_norm(triangle, 3);
        double linalg_ms = linalg_timer.elapsed_ms();

        if (correct && std::fabs(norm - 5.0) > 1e-9) {
            correct = false;
            failure = "vector_norm: expected 5.0 for a 3-4-5 triangle";
        }
        for (int i = 0; i < N && correct; ++i) {
            for (int j = 0; j < N; ++j) {
                if (std::fabs(T[j * N + i] - A[i * N + j]) > 1e-9) {
                    correct = false;
                    failure = "transpose: T[j][i] != A[i][j]";
                    break;
                }
            }
        }
        if (correct) {
            reference_matmul(A.data(), B.data(), Ref.data(), N);
            for (size_t i = 0; i < C.size() && correct; ++i) {
                if (std::fabs(C[i] - Ref[i]) > 1e-6) {
                    correct = false;
                    failure = "matmul: result did not match the reference implementation";
                }
            }
        }

        // --- sorting: quicksort + binary_search ---
        const int M = 5000;
        std::vector<int> arr(M);
        for (auto& x : arr) x = int_dist(rng);
        int target = arr[M / 2];

        Timer sort_timer;
        quicksort(arr.data(), 0, M - 1);
        double sort_ms = sort_timer.elapsed_ms();

        if (correct) {
            for (int i = 1; i < M; ++i) {
                if (arr[i - 1] > arr[i]) {
                    correct = false;
                    failure = "quicksort: output is not sorted";
                    break;
                }
            }
        }

        Timer search_timer;
        int idx = binary_search(arr.data(), M, target);
        double search_ms = search_timer.elapsed_ms();

        if (correct && (idx < 0 || arr[idx] != target)) {
            correct = false;
            failure = "binary_search: failed to find a value known to be present";
        }

        Metrics metrics;
        metrics.add("duration_ms", linalg_ms + sort_ms + search_ms);
        metrics.add("linalg_ms", linalg_ms);
        metrics.add("sorting_ms", sort_ms + search_ms);

        report(correct, metrics, correct ? "" : failure);
        return correct ? 0 : 1;
    });
}
