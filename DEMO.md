# OrbitGuard: 3-minute demo script
Before: open the Vercel URL (or `python app.py` locally), zoom the browser to 125 %, run the analysis once (so the DB is warm), then reload.

| Time | Beat | Do / say |
|---|---|---|
| 0:00 | Hook | "There are tens of thousands of tracked objects in orbit. In 2009 a dead Russian satellite hit a working Iridium satellite and created thousands of new fragments. Those fragments are in this data." |
| 0:20 | Solution | "OrbitGuard predicts every close approach for the next 24 hours, and explains it like a mission controller, fully offline." |
| 0:40 | Demo | Click **RUN ANALYSIS** → read the summary (objects, events, seconds). Point out cyan satellites vs orange debris. Drag the time slider. |
| 1:10 | Wow | Click the top **CRITICAL** event: the camera flies in, both orbit lines and the red pulsing marker appear. Click **SIMULATE BURN** at 0.2 m/s: the miss distance jumps and the risk drops. |
| 1:40 | AI | Click **AI MISSION BRIEFING** and let it type. |
| 2:00 | How | "SGP4 propagates every object in a second or two; a k-d tree finds nearby pairs at every 30-second step; then we solve for the exact time of closest approach. I checked it against brute force at 1-second resolution and it matches to the metre." Open **STATS**. |
| 2:30 | Impact | "Small satellite teams and students can't afford commercial conjunction services. Next: Kessler cascade mode and live data refresh." |
| 2:50 | Close | "OrbitGuard: see the crash before it happens." |

## Judge Q&A (2-sentence answers)
- **vs existing tools?** Space-Track/LeoLabs are operational services for operators; this is an open, offline, explainable tool for learning and early warning. It shows *why* a pass is risky.
- **Accuracy?** TCA and miss distance match brute-force propagation exactly; the input TLEs themselves are only accurate to about 1 km, so the probability is labelled as simplified.
- **When the AI is wrong?** The AI only explains numbers we computed and is told not to invent any. If it's unavailable, a rule-based briefing appears.
- **Data/security?** Public CelesTrak data only, no user data, runs locally.
- **Cost for 1,000 users?** Screening is about 3 s of CPU per run, so it can be cached hourly on one small server.
- **Hardest problem?** Fast head-on passes: two objects can close 450 km between samples, so we screen with a wide radius and solve for TCA analytically.
