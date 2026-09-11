from dataclasses import dataclass


@dataclass(frozen=True)
class TextDiagnosisRequest:
    source: str
    repository: str
    branch: str
    logs: str
