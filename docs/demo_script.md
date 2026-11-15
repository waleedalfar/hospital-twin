# Demo script (3 minutes)

Run `make demo` (stack plus the timed scenario helper) or `make dev` and drive it by hand. Say the lines in quotes.
Everything on screen is live: nothing is scripted except when the flu surge is started.

| Time | Do | Say |
| --- | --- | --- |
| 0:00 | Open the network map. | "Three hospitals, one simulated Phoenix day. Every dot is a patient record from Synthea; the data lands in Tiger Data." |
| 0:20 | Click **Mercy General**. | "This is Mercy in 3D. Every person is a live record: patients, nurses, doctors, EMTs." |
| 0:35 | Press **X-ray**, then the **ICU close-up** preset. | "X-ray shows through the walls. The ICU is where it matters." |
| 0:55 | Click the highest-risk ICU patient. | "The model scores everyone every five sim minutes. These are the top three reasons, from SHAP. Expected discharge comes from the length-of-stay model." |
| 1:15 | Menu **Scenario → Flu surge**, speed 8x. | "A flu surge hits Mercy. Arrivals go up two and a half times, mostly respiratory." |
| 1:35 | Watch the KPI strip and the feed. | "The waiting room fills. Oxygen saturation and respiratory rate shift, and the drift monitor fires." |
| 1:50 | **Governance → Drift**. | "PSI against the training data is red on SpO2 and respiratory rate. That is model drift, caught live." |
| 2:00 | Show the Agent panel. | "The agent recommends diverting ambulances, citing the ER occupancy, the waiting count and the other hospitals' load. Every number is checked against the data it was given; if Gemini is down a labelled rules engine takes over." |
| 2:15 | **Approve**. Go to the network map. | "Approving applies it to the simulation. Ambulances reroute to Desert Valley, and the audit log records who did what." |
| 2:30 | Back in Mercy: hold the mic (or type) "who is most likely to crash tonight". | "The answer is spoken, the patient is ringed in the building, and Fly to takes me there." |
| 2:45 | **Governance → Federated training**. | "Hospitals cannot pool records. Federated training shares only weights, and gets within 0.03 AUROC of centralized, above any hospital alone. I can switch the live model to it here." |
| 3:00 | Open the model card link. | "Data, metrics, fairness and limits, all generated from the run." |

Backup: `docs/demo.webm` (made by `make record`) shows the same flow.
