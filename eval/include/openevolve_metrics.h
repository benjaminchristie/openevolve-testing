/* Standard reporting contract for projects evaluated by eval/harness.py:
 * one line of JSON on stdout, {"status": "ok"|"error", "metrics": {...}}.
 * See openevolve_metrics.hpp for why this exists. Available without an
 * include-path hassle -- harness.py puts this directory on CPATH
 * automatically. Usage:
 *
 *     #include <openevolve_metrics.h>
 *
 *     void solve(void) { ... }  // the @evolve-tagged code
 *
 *     int main(void) {
 *         oe_timer_t t;
 *         oe_timer_start(&t);
 *         solve();
 *         int correct = check();
 *
 *         oe_metrics_t m;
 *         oe_metrics_init(&m);
 *         oe_metrics_add(&m, "duration_ms", oe_timer_elapsed_ms(&t));
 *         oe_report(correct, &m, correct ? "" : "result did not match expected value");
 *         return correct ? 0 : 1;
 *     }
 *
 * C has no exceptions to catch, so there's no oe_guarded() equivalent to the
 * C++/Python helpers -- just make sure solve() itself doesn't abort()/exit()
 * before oe_report() runs, or harness.py sees an opaque "no stdout output"
 * failure instead of a real error message.
 */
#ifndef OPENEVOLVE_METRICS_H
#define OPENEVOLVE_METRICS_H

#include <stdio.h>
#include <string.h>
#include <time.h>

typedef struct {
    struct timespec start;
} oe_timer_t;

static inline void oe_timer_start(oe_timer_t* t) {
    timespec_get(&t->start, TIME_UTC);
}

static inline double oe_timer_elapsed_ms(const oe_timer_t* t) {
    struct timespec end;
    timespec_get(&end, TIME_UTC);
    return (end.tv_sec - t->start.tv_sec) * 1000.0 + (end.tv_nsec - t->start.tv_nsec) / 1e6;
}

/* Fixed-size buffer is enough for a handful of named metrics; grow OE_METRICS_BUF_SIZE
 * if a project reports more than that. */
#define OE_METRICS_BUF_SIZE 1024

typedef struct {
    char buf[OE_METRICS_BUF_SIZE];
    int first;
} oe_metrics_t;

static inline void oe_metrics_init(oe_metrics_t* m) {
    m->buf[0] = '\0';
    m->first = 1;
}

static inline void oe_metrics_add(oe_metrics_t* m, const char* name, double value) {
    char tmp[160];
    size_t used = strlen(m->buf);
    if (used >= sizeof(m->buf) - 1) return; /* silently drop past capacity rather than overflow */
    snprintf(tmp, sizeof(tmp), "%s\"%s\": %f", m->first ? "" : ", ", name, value);
    strncat(m->buf, tmp, sizeof(m->buf) - used - 1);
    m->first = 0;
}

static inline void oe_json_escape_into(char* dst, size_t dst_size, const char* src) {
    size_t di = 0;
    size_t si;
    for (si = 0; src[si] != '\0' && di + 2 < dst_size; ++si) {
        char c = src[si];
        if (c == '"' || c == '\\') {
            dst[di++] = '\\';
        }
        if (c == '\n') {
            dst[di++] = '\\';
            dst[di++] = 'n';
            continue;
        }
        dst[di++] = c;
    }
    dst[di] = '\0';
}

/* message may be NULL or "" to omit the "message" field. */
static inline void oe_report(int ok, const oe_metrics_t* metrics, const char* message) {
    printf("{\"status\": \"%s\", \"metrics\": {%s}", ok ? "ok" : "error", metrics->buf);
    if (message != NULL && message[0] != '\0') {
        char escaped[512];
        oe_json_escape_into(escaped, sizeof(escaped), message);
        printf(", \"message\": \"%s\"", escaped);
    }
    printf("}\n");
}

#endif /* OPENEVOLVE_METRICS_H */
