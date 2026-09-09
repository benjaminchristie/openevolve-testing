import json
import time


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

    start = time.perf_counter()
    C = matrix_multiply(A, B, N)
    duration_ms = (time.perf_counter() - start) * 1000

    expected = N * 1.0 * 2.0
    correct = all(abs(v - expected) < 1e-6 for v in C)

    # Same one-JSON-line-on-stdout contract as every other project.yaml-driven
    # project (see eval/harness.py) -- this is what makes the harness generic
    # across languages: any language that can print a line of text can honor
    # this same contract, so eval/harness.py doesn't need to know Python from
    # C++ from anything else.
    result = {"status": "ok" if correct else "error", "metrics": {"duration_ms": duration_ms}}
    if not correct:
        result["message"] = "result did not match expected value"
    print(json.dumps(result))


if __name__ == "__main__":
    main()
