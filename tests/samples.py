"""A sample meeting and good / bad answers for it, shared by the tests."""
import copy

MEETING = """Maria Santos: Good morning, everyone. Today we need to settle the launch date for the new blend.
Ben Cruz: Design is almost done. I'll send the final label files to the printer by Friday.
Ana Reyes: The roaster can deliver on the 10th. Are we sure about the price of 450 pesos?
Maria Santos: We agreed last week on 450 pesos, so let's keep it.
Ben Cruz: Then we'll go with December 15 for the launch.
Maria Santos: Good. Ana, can you book the photographer for the product photos?
Ana Reyes: Yes, I will book the photographer tomorrow.
Ben Cruz: One question nobody answered yet: who writes the newsletter?
"""

GOOD = {
    "title": "New blend launch",
    "overview": "The team set the launch of the new blend. They kept the price and chose December 15.",
    "key_points": [{"text": "Design for the new blend is almost done.",
                    "evidence": [{"line": 2, "quote": "Design is almost done."}]}],
    "decisions": [
        {"text": "The price stays at 450 pesos.", "rationale": "It was agreed last week.",
         "evidence": [{"line": 4, "quote": "We agreed last week on 450 pesos, so let's keep it."}]},
        {"text": "The launch is on December 15.", "rationale": None,
         "evidence": [{"line": 5, "quote": "we'll go with December 15 for the launch"}]},
    ],
    "action_items": [
        {"task": "Send the final label files to the printer", "owner": "Ben Cruz", "due_phrase": "by Friday",
         "due_date": "2026-11-27", "priority": "high",
         "evidence": [{"line": 2, "quote": "I'll send the final label files to the printer by Friday."}]},
        {"task": "Book the photographer for the product photos", "owner": "Ana Reyes", "due_phrase": "tomorrow",
         "due_date": "2026-11-25", "priority": "medium",
         "evidence": [{"line": 7, "quote": "I will book the photographer tomorrow"}]},
    ],
    "open_questions": [{"text": "Who writes the newsletter?",
                        "evidence": [{"line": 8, "quote": "who writes the newsletter?"}]}],
}


def good(**changes):
    answer = copy.deepcopy(GOOD)
    answer.update(changes)
    return answer


def with_action(**changes):
    """GOOD with its first action item changed."""
    answer = copy.deepcopy(GOOD)
    answer["action_items"][0].update(changes)
    return answer
