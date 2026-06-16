"""
Multi-Agent Credit Risk Platform
=================================
Each agent owns a discrete functional domain and communicates via
well-defined contracts (see schemas/contracts.py).

Agent registry:
  DataIngestionAgent       — ingest, validate, normalise raw data
  FeatureEngineeringAgent  — compute & store credit features
  RiskModelingAgent        — train / score PD / fraud models
  DecisionEngineAgent      — apply rules + ML scores → decision
  ExplainabilityAgent      — SHAP reason codes + compliance text
  MonitoringAgent          — PSI drift + fair-lending surveillance
  ExperimentationAgent     — champion/challenger A/B framework
"""

from agents.base import BaseAgent, AgentResult, AgentStatus  # noqa: F401
