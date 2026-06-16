import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';

// Read the sample payload from the file system
const payload = new SharedArray('sample applicant', function () {
    return [JSON.parse(open('../data/sample_applicant.json'))];
});

export const options = {
    stages: [
        { duration: '30s', target: 20 }, // Stage 1 (ramp up): 0 -> 20 VUs over 30s
        { duration: '2m', target: 20 },  // Stage 2 (sustained): 20 VUs for 2 minutes
        { duration: '1m', target: 50 },  // Stage 3 (peak): 50 VUs for 1 minute
        { duration: '30s', target: 0 },  // Stage 4 (ramp down): 50 -> 0 VUs over 30s
    ],
    thresholds: {
        http_req_duration: ['p(95)<500', 'p(99)<1000'],
        http_req_failed: ['rate<0.01'], // < 1%
    },
    summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

export default function () {
    const url = 'http://host.docker.internal:8000/v1/decisions';
    const jwtToken = __ENV.BENCHMARK_JWT || "dummy-token";
    const params = {
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${jwtToken}`,
        },
    };

    const res = http.post(url, JSON.stringify(payload[0]), params);

    check(res, {
        'status is 200': (r) => r.status === 200,
    });

    sleep(0.5);
}
