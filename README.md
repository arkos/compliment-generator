# Compliment Generator

A lightweight Flask microservice with a static command-center dashboard, built as a portfolio foundation for Kubernetes deployment and observability.

The dashboard displays a random compliment alongside its request correlation ID, UTC timestamp, client latency, and raw JSON response. The service exposes Kubernetes probes, Prometheus metrics, and structured JSON logs.

## Features

- Flask API served by Gunicorn with two workers and four threads per worker by default.
- Static HTML, vanilla CSS, and vanilla JavaScript; no frontend build step.
- Responsive dark UI using Inter and JetBrains Mono.
- Unique request correlation IDs in API responses, response headers, and logs.
- Prometheus request counters and latency histograms with bounded labels.
- Metrics aggregated across Gunicorn workers within each container.
- Non-root Docker image based on Python 3.12 slim.
- Kubernetes deployment with two replicas, probes, resource limits, and a read-only root filesystem.

Prometheus/Grafana installation and Kubernetes manifests are documented below. GitOps, centralized log collection, and distributed tracing are future extensions, not application features already implemented.

## Source layout

| File | Purpose |
| --- | --- |
| `app.py` | API, static serving, probes, instrumentation, and JSON logging |
| `static/index.html` | Dashboard markup |
| `static/styles.css` | Responsive styling and palette variables |
| `static/script.js` | API requests, timeout handling, and DOM updates |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Non-root container and Gunicorn startup |
| `README.md` | Setup and operations |

Create `k8s.yaml`, `monitoring-values.yaml`, and `servicemonitor.yaml` from the examples below if they are not already in your repository.

## Architecture

The browser calls Flask through the Kubernetes Service. The Service selects application pods, each running Gunicorn workers. Prometheus discovers each pod endpoint through a ServiceMonitor and scrapes it directly. Grafana queries Prometheus for visualization.

Request logs go to container stdout and can be inspected with `kubectl logs`. A centralized log collector is not installed by these instructions.

## Prerequisites

- Docker
- Minikube
- kubectl
- Helm for the monitoring stack
- Python 3.12 for optional development outside Docker

On Windows, run commands in WSL2 Ubuntu with Docker Desktop's WSL integration enabled. Commands assume the repository root is your working directory.

Check your tools:

```bash
docker info
minikube version
kubectl version --client
helm version
```

## Run with Docker

```bash
docker build -t compliment-generator:local .
docker run --rm --name compliment-generator -p 8080:8080 compliment-generator:local
```

Open [http://localhost:8080](http://localhost:8080).

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8080` | Container HTTP listening port |
| `WEB_CONCURRENCY` | `2` | Number of Gunicorn workers |
| `PROMETHEUS_MULTIPROC_DIR` | Created at startup | Shared worker metrics directory |

The Docker startup command creates a fresh metrics directory under `/tmp` and exports it before Python starts. Do not replace the startup command with multi-worker Gunicorn without configuring multiprocess metrics.

## Optional local development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app run --debug --port 8080
```

Use Flask's development server only for local development. With no multiprocess environment variable, the application exposes metrics from its current process.

## HTTP endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Command-center dashboard |
| GET | `/api/v1/compliments/random` | Random compliment and request metadata |
| GET | `/healthz` | Liveness; returns `200 OK` |
| GET | `/readyz` | Readiness; returns `200 OK` |
| GET | `/metrics` | Prometheus exposition |

Example request:

```bash
curl -i http://localhost:8080/api/v1/compliments/random
```

Example response:

```json
{
  "compliment": "Your curiosity makes every project stronger.",
  "trace_id": "4d8a9c773b314d2097d41aee3e6c0f65",
  "timestamp": "2026-10-07T12:00:00.000+00:00"
}
```

Responses include `X-Trace-ID` and `Server-Timing` headers. API responses use `Cache-Control: no-store`. The trace ID is a correlation ID; there are no distributed tracing spans.

The service has no external dependencies, so readiness currently checks the same basic application availability as liveness.

## Deploy to Minikube

### Start the cluster and build the image

For a new cluster including monitoring, 4 CPUs and 6 GiB RAM provide a practical starting allocation if your host has capacity:

```bash
minikube start --driver=docker --cpus=4 --memory=6144
kubectl config use-context minikube
kubectl get nodes
minikube image build -t compliment-generator:local .
```

If your cluster is already running, reuse it and build the image. Check scheduling events if the monitoring stack exhausts available capacity.

### Create k8s.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: compliment-generator
  namespace: default
  labels:
    app: compliment-generator
spec:
  replicas: 2
  selector:
    matchLabels:
      app: compliment-generator
  template:
    metadata:
      labels:
        app: compliment-generator
    spec:
      terminationGracePeriodSeconds: 40
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: app
          image: compliment-generator:local
          imagePullPolicy: Never
          ports:
            - name: http
              containerPort: 8080
          env:
            - name: WEB_CONCURRENCY
              value: "2"
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: "1"
              memory: 256Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
          startupProbe:
            httpGet:
              path: /healthz
              port: http
            periodSeconds: 2
            failureThreshold: 30
          livenessProbe:
            httpGet:
              path: /healthz
              port: http
            periodSeconds: 10
            timeoutSeconds: 2
          readinessProbe:
            httpGet:
              path: /readyz
              port: http
            periodSeconds: 5
            timeoutSeconds: 2
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: compliment-generator
  namespace: default
  labels:
    app: compliment-generator
spec:
  selector:
    app: compliment-generator
  ports:
    - name: http
      port: 80
      targetPort: http
  type: ClusterIP
```

The writable `/tmp` volume supports Gunicorn temporary files and Prometheus worker metrics. Kubernetes uses the configured probes; it does not use the Docker HEALTHCHECK.

### Apply and access

```bash
kubectl apply -f k8s.yaml
kubectl rollout status deployment/compliment-generator -n default --timeout=120s
kubectl get pods -n default -l app=compliment-generator
kubectl port-forward -n default service/compliment-generator 8080:80
```

Leave port-forwarding running and open [http://localhost:8080](http://localhost:8080). A Service port-forward selects a single pod; this access method does not demonstrate load balancing across replicas.

### Update the application

After changing source files:

```bash
minikube image build -t compliment-generator:local .
kubectl rollout restart deployment/compliment-generator -n default
kubectl rollout status deployment/compliment-generator -n default
```

The local setup deliberately uses `imagePullPolicy: Never`. For a registry-backed deployment, use published immutable image tags or digests and an appropriate pull policy.

## Install Prometheus and Grafana

The Python client records metrics; it does not install a Prometheus server. Prometheus scrapes and stores historical samples, and Grafana visualizes them.

### Create monitoring-values.yaml

```yaml
alertmanager:
  enabled: false

grafana:
  enabled: true
  persistence:
    enabled: false
  resources:
    requests:
      cpu: 50m
      memory: 256Mi
    limits:
      memory: 1Gi

prometheus:
  prometheusSpec:
    retention: 24h
    scrapeInterval: 15s
    evaluationInterval: 15s
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        memory: 768Mi
    serviceMonitorNamespaceSelector:
      matchLabels:
        kubernetes.io/metadata.name: monitoring
    serviceMonitorSelector:
      matchLabels:
        release: monitoring

kubeEtcd:
  enabled: false
kubeControllerManager:
  enabled: false
kubeScheduler:
  enabled: false
kubeProxy:
  enabled: false
```

Grafana's memory limit is 1 GiB because 256 MiB caused OOM kills in this local installation. Adjust resources using observed usage.

Storage is ephemeral: Grafana UI-created dashboards and Prometheus history can disappear when their pods are replaced. Export dashboards and add persistent volumes before treating the stack as durable infrastructure.

### Install the chart

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --values monitoring-values.yaml --wait --timeout 10m
kubectl get pods -n monitoring
```

For reproducible environments, record and pin the chart version with `--version`. Reusing an unpinned command later can upgrade the chart as well as its configuration.

### Create servicemonitor.yaml

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: compliment-generator
  namespace: monitoring
  labels:
    release: monitoring
spec:
  namespaceSelector:
    matchNames:
      - default
  selector:
    matchLabels:
      app: compliment-generator
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
      scrapeTimeout: 5s
```

```bash
kubectl apply -f servicemonitor.yaml
```

The monitor's selector matches Service metadata labels, not only the Service's pod selector. Its `http` port matches the named Service port. Prometheus discovers and scrapes each application pod separately. Scrape annotations are unnecessary for this configuration.

### Open the monitoring interfaces

Run each port-forward in its own terminal or tmux pane:

```bash
kubectl port-forward -n monitoring service/monitoring-kube-prometheus-prometheus 9090:9090
```

```bash
kubectl port-forward -n monitoring service/monitoring-grafana 3000:80
```

- Prometheus targets: [http://localhost:9090/targets](http://localhost:9090/targets)
- Grafana: [http://localhost:3000](http://localhost:3000)
- Grafana username: `admin`

Retrieve the generated Grafana password:

```bash
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath='{.data.admin-password}' | base64 --decode
```

Do not commit the password to Git. The chart provisions the Prometheus data source automatically.

Verify two successful scrape targets in Prometheus:

```promql
up{namespace="default", service="compliment-generator"}
```

Each target should have value `1`.

## Metrics and logs

| Metric | Type | Labels |
| --- | --- | --- |
| `compliment_http_requests_total` | Counter | method, route, status |
| `compliment_http_request_duration_seconds` | Histogram | method, route |

The histogram exposes `_bucket`, `_sum`, and `_count` series. Buckets are 5, 10, 25, 50, 100, 250, and 500 ms, then 1, 2.5, and 5 seconds, plus infinity.

Probes and scrapes are excluded from request metrics and normal request logs. Other requests, including static assets, are instrumented; filter by route for API-only panels. Route templates bound label cardinality. Trace IDs are never metric labels.

Metrics aggregate workers within a pod, not across pods. Prometheus queries aggregate across replicas. Local counters reset when the container starts again.

Inspect request logs:

```bash
kubectl logs -n default -l app=compliment-generator --tail=20 --prefix=true
```

Example JSON log (the kubectl prefix, if enabled, appears outside this JSON):

```json
{
  "timestamp": "2026-10-07T12:00:00.001+00:00",
  "level": "INFO",
  "service": "compliment-generator",
  "logger": "app",
  "message": "http_request",
  "trace_id": "4d8a9c773b314d2097d41aee3e6c0f65",
  "method": "GET",
  "route": "/api/v1/compliments/random",
  "status": 200,
  "duration_ms": 0.42
}
```

## Generate traffic

With the application port-forward running:

```bash
for i in $(seq 1 180); do
  curl --fail --silent --output /dev/null http://localhost:8080/api/v1/compliments/random
  sleep 1
done
```

This generates approximately one request per second for three minutes against the forwarded pod.

## Grafana dashboard

Create a dashboard named **Compliment Generator**, select the **Prometheus** data source, and use the query editor's **Code** mode. Set the time range to **Last 15 minutes** and refresh to **15 seconds**.

### Request rate

Time series; unit requests/second:

```promql
sum(rate(compliment_http_requests_total{
  namespace="default", service="compliment-generator",
  route="/api/v1/compliments/random"
}[5m]))
```

### Average API latency

Time series; unit milliseconds:

```promql
1000 *
sum(rate(compliment_http_request_duration_seconds_sum{
  namespace="default", service="compliment-generator",
  route="/api/v1/compliments/random"
}[5m]))
/
sum(rate(compliment_http_request_duration_seconds_count{
  namespace="default", service="compliment-generator",
  route="/api/v1/compliments/random"
}[5m]))
```

### P95 API latency

Time series; unit milliseconds:

```promql
1000 * histogram_quantile(0.95,
  sum by (le) (rate(compliment_http_request_duration_seconds_bucket{
    namespace="default", service="compliment-generator",
    route="/api/v1/compliments/random"
  }[5m]))
)
```

P95 is estimated from buckets. The 5 ms lowest bucket provides limited precision for a sub-millisecond API. Server metrics measure Flask handling time, whereas frontend latency includes the network round trip and response reading.

### Reachable application targets

Stat panel; instant query:

```promql
sum(up{namespace="default", service="compliment-generator"})
```

Expected value: `2`. This measures successful scrapes, not Kubernetes readiness.

### Server errors per second

Time series:

```promql
sum(rate(compliment_http_requests_total{
  namespace="default", service="compliment-generator",
  route="/api/v1/compliments/random", status=~"5.."
}[5m])) or vector(0)
```

An absent 5xx series is displayed as zero. Check scrape health alongside this panel to distinguish no errors from a missing target.

Rate calculations need at least two scrape samples. Latency has no meaningful value when there are no requests in the selected five-minute window.

## Troubleshooting

### Image cannot be started

```bash
minikube image build -t compliment-generator:local .
kubectl describe pods -n default -l app=compliment-generator
```

Confirm the image name matches the Deployment and the build used the same Minikube profile.

### Grafana connection refused or port-forward terminated

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
kubectl describe pods -n monitoring -l app.kubernetes.io/name=grafana
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana --tail=80
```

If the container restarted, inspect its previous logs:

```bash
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana --previous --tail=80
```

`OOMKilled` indicates a memory-related termination; check container limits and node capacity. Update Helm values and apply them using the installed chart version. Restart port-forwarding after the pod recovers.

### Application absent from Prometheus targets

```bash
kubectl get servicemonitor -n monitoring
kubectl get service compliment-generator -n default --show-labels
kubectl get endpointslices -n default -l kubernetes.io/service-name=compliment-generator
```

Check the Service's `app=compliment-generator` label, monitor's `release=monitoring` label, namespaces, named port, and pod readiness.

### Monitoring pods remain Pending

```bash
kubectl get events -n monitoring --sort-by=.lastTimestamp
kubectl describe node minikube
```

Inspect scheduling messages for insufficient resources. The node must have enough allocatable capacity for the application's requests and monitoring components.

### Browser cannot connect

Keep port-forward terminals running. From WSL, test:

```bash
curl -i --max-time 5 http://localhost:3000/api/health
```

If WSL succeeds but Windows fails, investigate Windows-to-WSL localhost forwarding. If Grafana's frontend asset error appears, try a hard refresh or private browser window and inspect Grafana logs.

## Cleanup

Remove application resources:

```bash
kubectl delete -f servicemonitor.yaml
kubectl delete -f k8s.yaml
```

Remove the monitoring Helm release:

```bash
helm uninstall monitoring -n monitoring
```

Operator CRDs may remain after Helm uninstall. Stop Minikube when you are done:

```bash
minikube stop
```

## Future work

- GitHub Actions for tests, image builds, and registry publishing.
- Immutable image references and dependency/chart version locking.
- Argo CD for GitOps reconciliation.
- Persistent monitoring storage and dashboards provisioned from Git.
- Prometheus alert rules and Alertmanager routing.
- Fluent Bit with a centralized log backend.
- OpenTelemetry instrumentation and a tracing backend.
- Ingress, TLS, and network policies.

The application provides a foundation for these capabilities; it is not a complete production platform. Google Fonts requires browser internet access, with system fonts available as fallbacks.

## References

- [Flask documentation](https://flask.palletsprojects.com/)
- [Gunicorn documentation](https://docs.gunicorn.org/)
- [Prometheus Python client multiprocess mode](https://prometheus.github.io/client_python/multiprocess/)
- [Minikube documentation](https://minikube.sigs.k8s.io/docs/)
- [kube-prometheus-stack chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Prometheus Operator documentation](https://prometheus-operator.dev/)
- [Grafana documentation](https://grafana.com/docs/grafana/latest/)

