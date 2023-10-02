from spacy.matcher import Matcher
import spacy

nlp = spacy.load("en_core_web_sm")
matcher = Matcher(nlp.vocab)

# Pattern to identify sentences like "I am [PERSON] and I am sick"
sick_person_pattern = [{"LOWER": "i"}, {"LOWER": "am"}, {"ENT_TYPE": "PERSON"}, {"LOWER": "and"}, {"LOWER": "i"}, {"LOWER": "sick"}]

# Another pattern to identify sentences like "I am on [CARDINAL] days MC"
mc_days_pattern = [{"LOWER": "i"}, {"LOWER": "am"}, {"LOWER": "on"}, {"ENT_TYPE": "CARDINAL"}, {"LOWER": "days"}, {"LOWER": "mc"}]

# Add patterns to the matcher
matcher.add("identify_sick_person", [sick_person_pattern])
matcher.add("identify_mc_days", [mc_days_pattern])

def match_info(text):
    doc = nlp(text)
    matches = matcher(doc)
    for match_id, start, end in matches:
        string_id = nlp.vocab.strings[match_id]
        span = doc[start:end]
        print(f"{string_id}: {span.text}")

# Test the function
match_info("I am Rachel and I am sick and on 3 days MC")