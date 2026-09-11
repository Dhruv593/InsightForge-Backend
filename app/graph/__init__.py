__all__ = ["AnalysisWorkflow"]


def __getattr__(name):
    # Topology inspection must not import provider SDKs or application settings.
    if name == "AnalysisWorkflow":
        from app.graph.workflow import AnalysisWorkflow
        return AnalysisWorkflow
    raise AttributeError(name)
