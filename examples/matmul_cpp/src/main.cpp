#include <cmath>
#include <vector>

#include <openevolve_metrics.hpp>
using namespace openevolve;

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
    return guarded([]() {
        const int N = 512;
        std::vector<double> A(N * N, 1.0);
        std::vector<double> B(N * N, 2.0);
        std::vector<double> C(N * N, 0.0);

        Timer t;
        matrix_multiply(A, B, C, N);
        double duration_ms = t.elapsed_ms();

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

        report(correct, Metrics().add("duration_ms", duration_ms),
               correct ? "" : "result did not match expected value");
        return correct ? 0 : 1;
    });
}
