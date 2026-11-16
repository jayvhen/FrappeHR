# novacore_integrations

External-system connectors for NovaCore HRIS (Package Diagram: `novacore_integrations`).
Configure endpoints in **NovaCore Integration Settings**. Every outbound call is logged in
**Integration Request**. When a connector is disabled, the app falls back to a manual
workflow (ToDo for IT, or a downloadable bank file) so nothing is silently skipped.

| Connector | Direction | Endpoint / trigger |
|---|---|---|
| Biometric terminals | inbound | `POST /api/method/novacore_integrations.connectors.biometric.push_checkins` |
| Bank payroll API | outbound | after payroll approval |
| KPI / QA system | in + out | `push_kpis` endpoint, or `import_kpis` pull |
| AD / Microsoft 365 | outbound | employee onboarding / separation |
| Job boards | outbound | Job Opening with "Publish to Job Boards" |
| E-signature | out + webhook | Job Offer "Send for e-Signature" |
