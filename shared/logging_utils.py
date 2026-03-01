import os
from opencensus.ext.azure.metrics_exporter import MetricsExporter
from opencensus.stats import stats as stats_module

_exporter = None

def metrics_client():
    global _exporter
    if _exporter is None:
        conn = os.getenv("APPINSIGHTS_INSTRUMENTATIONKEY")
        if conn:
            _exporter = MetricsExporter(connection_string=f"InstrumentationKey={conn}")
    return _Metrics(_exporter)

class _Metrics:
    def __init__(self, exporter):
        self.exporter = exporter
        self.stats = stats_module.Stats()
        self.view_manager = self.stats.view_manager
        self.stats_recorder = self.stats.stats_recorder

    def track_metric(self, name: str, value: float):
        try:
            if not self.exporter:
                return
            pass  # placeholder for opencensus measure/view registration
        except Exception:
            pass