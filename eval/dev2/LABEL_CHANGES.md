# dev2 label changes (ACC1, 2026-10-26)
Rule used: README label rules (street/bairro without number + life risk -> SEND_APPROX). Only labels contradicting the written rule were changed;
no label was changed because of what the system output.
- d2-047 CALLBACK/incomplete -> SEND_APPROX/street: "preciso de resgate" is an explicit rescue request (life-safety), street found, no number.
- d2-050: partial ACC1 changed CALLBACK/incomplete -> SEND_APPROX/street; ACC1b reverses it to CALLBACK/incomplete as explicitly required by the resumed brief. A generic heading without an exact point or physical-danger description needs confirmation. This is a conservative exception to the original broad life-risk reading; it is not counted as a label-based accuracy gain.
- d2-052 CALLBACK/incomplete -> SEND_APPROX/street: "ilhados, sem comida" is life risk; same rule.
Kept (system fixed instead): d2-032, 086, 089-091, 108, 167, 169, 172, 176-178.
- d2-082..086 expected_route not_a_rescue -> volunteer_offer: the desk has a dedicated 'oferta de ajuda' route (routing.py F6); decision (REVIEW) unchanged.
- d2-167 expected_route not_a_rescue -> volunteer_offer for the same dedicated offer route; decision REVIEW unchanged.
