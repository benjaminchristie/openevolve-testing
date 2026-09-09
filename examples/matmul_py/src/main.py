from openevolve_metrics import Timer, report, guarded


# @evolve
def matrix_multiply(A, B, N):
    C = [0.0] * (N * N)
    for i in range(N):
        for j in range(N):
            s = 0.0
            for k in range(N):
                s += A[i * N + k] * B[k * N + j]
            C[i * N + j] = s
    return C


def main():
    N = 64
    A = [1.0] * (N * N)
    B = [2.0] * (N * N)

    with Timer() as t:
        C = matrix_multiply(A, B, N)

    expected = N * 1.0 * 2.0
    correct = all(abs(v - expected) < 1e-6 for v in C)

    report(
        status="ok" if correct else "error",
        metrics={"duration_ms": t.elapsed_ms},
        message=None if correct else "result did not match expected value",
    )


if __name__ == "__main__":
    guarded(main)
