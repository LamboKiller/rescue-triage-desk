# Arca — speaker notes

## Slide 01 — Arca: AI agents for flood rescue

In May 2024 the worst floods in the history of Rio Grande do Sul, in southern Brazil, put whole cities under water. People asked for help any way they could, and many requests were hard to read, hard to locate, or simply lost in the noise. We built Arca, Portuguese for ark: a team of AI agents that reads every request, finds the place, plans the rescue and hands it to a human dispatcher, who approves every boat that leaves. This is a replay of 6 May 2024.

## Slide 02 — 185 lives lost

The scale first. One hundred and eighty-five people died. Two point four million were affected, in 478 of the state's 497 municipalities. On the right is the Guaíba river at Porto Alegre: it peaked at 5.35 metres, above the 1941 record of 4.76. Whole neighbourhoods stayed under water for weeks, and rescue was done street by street, by boat. Every number on this slide comes from Defesa Civil's final bulletin and the Brazilian Geological Service; sources are in the appendix.

## Slide 03 — Calls came from everywhere

More than 77,000 people were rescued, many by volunteers in their own boats. The requests arrived through dozens of WhatsApp groups, phone calls, social media posts and single texts sent with the last bar of signal. The volunteers were brave and fast; what they lacked was one shared picture of who needed help, where, and how urgently. Arca is built for the municipal Defesa Civil dispatch rooms and the volunteer rescue coordinators who face that flood of requests.

## Slide 04 — A strong El Niño is coming again

Why now. NOAA's Climate Prediction Center, in its 8 October 2026 discussion, gives a better-than-83 percent chance of a strong to very strong El Niño through early 2027. El Niño years bring heavy rain to southern Brazil. We cannot say when the next flood comes, but the planning window is short, and the next time requests flood in, the people answering them should not be reading messages one by one with no shared picture.

## Slide 05 — One call for help

Here is one call for help, followed end to end. A woman writes on WhatsApp: socorro, we are on the second floor at Voluntários da Pátria 1067, Porto Alegre, me, my bedridden mother and my 8-year-old son, the water won't stop rising. Our agents read it in Portuguese, as written. They count three people, see that the mother is bedridden, so this is medical and P1, top priority, and they verify the street address in Zetaris. On the right is the case card Arca produced, live.

## Slide 06 — Agents check each other's work, live

This is how the agents handle that message. Intake reads it, the Location agent finds the street through Zetaris, and checker agents challenge the reading: a critic, a credibility reviewer, a hazard checker and a duplicate reviewer. An objection sends it back and Intake re-reads the message. Only then does a proposal reach a human dispatcher. Every model call carries a Nemotron receipt with model, receipt id and time, and every fact quotes the exact words it came from: minha mãe acamada, my mother is bedridden.

## Slide 07 — The agents plan the rescue. A person approves it.

Then the planning agents take over. The fleet agent checks every boat on shift and finds the one that can reach her: here, a simulated aluminium boat for six, 24 minutes away. Routing plans the road to the water's edge, then the water leg by boat, which is an estimate: 8.9 kilometres in total. Nothing moves until a human dispatcher ticks five safety checks and presses Dispatch, and even then there are ten seconds to undo. When the crew reports resgatamos 3, we rescued 3, the case closes.

## Slide 08 — How the agents work together

Here is the whole team on one page. 28 agents and loops, 19 of them model agents and 9 operational loops, work in four stages: read, plan, watch, and a human who approves. Three loops keep the picture current: the callback agent asks the citizen one question on the same channel the request came from and re-reads the reply, a new P1 can reroute a boat, and the supervisor keeps alerting until a problem is closed. Underneath, the Meterless World Model keeps one shared event log: every agent action recorded and replayable.

Full roster (counted from agents_roster.json; 19 model agents + 9 operational loops):

- **Intake** (model agent): Extracts people, places and risks with exact source quotes.
- **Needs** (model agent): Reads vulnerabilities and medical needs from cited messages.
- **Critic** (model agent): Challenges uncertain readings with objections.
- **Verifier** (model agent): Proposes checked corrections to extracted fields.
- **Revision** (model agent): Re-reads the message after critic objections.
- **Location** (model agent): Searches streets and landmarks through bounded tool turns.
- **Credibility** (model agent): Reviews source signals without discarding people needing help.
- **Duplicates** (model agent): Reviews whether reports describe the same incident.
- **Hazard** (model agent): Reviews conflicts between the message and flood evidence.
- **Contradictions** (model agent): Phrases a question when cited sources disagree.
- **Arbiter** (model agent): Selects a supported claim or escalates a conflict.
- **Callback** (model agent): Asks targeted questions and re-triages the citizen reply.
- **Fleet** (model agent): Explains the ranked asset choices and cautions.
- **Mission brief** (model agent): Explains the proposed mission to the crew.
- **Field feedback** (model agent): Extracts rescue counts and status from crew reports.
- **Volunteer intake** (model agent): Reads offers of boats and equipment for human verification.
- **Supervisor** (model agent): Ranks findings while the supervisor loop rechecks closure conditions.
- **Handover** (model agent): Summarizes verified facts for the next shift.
- **Red team** (model agent): Generates declared adversarial requests before the trial runs. (development tooling; not on the slides)
- **Surge intake** (operational loop): Persists every accepted request and prioritizes the waiting queue.
- **Shelter** (operational loop): Tracks vacancies and full shelters and recommends destinations.
- **Reunite** (operational loop): Suggests evidence-bearing family matches for human confirmation.
- **Mission planner** (operational loop): Groups neighbours and proposes resource and capacity compatible missions.
- **Routing** (operational loop): Computes road legs and depth-grid water legs.
- **Landing** (operational loop): Proposes landing choices and onward medical transport.
- **Unit status** (operational loop): Tracks crew status and signal or idle gaps.
- **Place memory** (operational loop): Stores proposed aliases that gain authority only after human approval.
- **Red-team judge** (operational loop): Scores declared attacks and proposes human-approved regressions. (development tooling; not on the slides)

## Slide 09 — Built safety-first. Tested hard.

We built this safety-first and tested it hard. On live requests the agents triage 29 of 30 correctly, in 11 seconds on average. They stopped all 42 red-team attacks. On 100 never-seen blind requests, run once live, 94 recommendations were safe. To be exact: 34 of 50 and 29 of 50 correct, with 3 unsafe sends in each set, so the blind gap is our next work. When unsure, the agents ask again instead of guessing, and no boat moves without a human.

## Slide 10 — Built on

Three sponsor technologies carry the system. NVIDIA Nemotron is the model behind every agent decision, and every call leaves a receipt we can audit. Meterless Nightshift is the single gateway every agent call goes through, and our event log follows the Meterless World Model: one shared, replayable record of every agent action. Zetaris holds the city: streets, landmarks and flood data, queried in one place, which is how the agents verified Voluntários da Pátria 1067 in the demo.

## Slide 11 — The technical stack

Under the hood the stack is small on purpose. The agents run on NVIDIA Nemotron, reached through Meterless Nightshift. The Meterless World Model engine keeps one event log of every action. Zetaris serves place and flood data through REST, S3 and USL views, next to an OpenStreetMap road graph. The app itself is a Python standard-library server with an HTTP run API, shipped in Docker, and SAMPLE_MODE runs the whole desk offline with no keys. What is unique: agents cite their receipts, and every decision can be replayed.

## Slide 12 — What comes next

What comes next. First, intake where people already ask for help: the WhatsApp Business API and the 193 fire-brigade line, feeding the same queue. Second, live river gauges for the Guaíba, Jacuí and Taquari through Zetaris, replacing retrospective flood layers with observed levels. Third, a Defesa Civil pilot before the next El Niño season: a tabletop exercise on replayed messages, then a supervised pilot. And before any real use, we close the gap on the blind tests.

## Slide 13 — Every request heard

Every request heard. Every agent working together. When the next flood comes, no call for help should get lost. Today this is a replay of 6 May 2024 with a simulated fleet and GPS; we do not claim lives saved, only the potential. Our ask is concrete: help us pilot it with Defesa Civil before the next El Niño, with real dispatchers, real channels and real boats, measured honestly. The code, the evaluations and this deck are open at github.com/LamboKiller/rescue-triage-desk.

## Slide 14 — Appendix · Sources & credits

Every number in the deck, with its source and date, and every photograph with author and licence; full URLs are in CREDITS.md. The hero message is a synthetic case written for the replay; the product frames are live captures of Arca on 27 October 2026 with real Nemotron calls through Nightshift. The fleet, GPS, shelter and ambulance data are simulated. Development tooling not shown on the slides, such as our red-team generator, is described in the repository.

