"""Reject ambiguous duplicate recovery without rewriting legacy charge records."""
import re,unicodedata
from billing_calculator import BillingValidationError


def normalized_name(name):
    name=unicodedata.normalize('NFKC',name).casefold()
    words=re.findall(r'\w+',name)
    while words and words[-1] in ('expense','expenses','bill','charge','charges'):words.pop()
    return ' '.join(words)


def reject_duplicate_sources(expenses,rules):
    for source in expenses:
        name=normalized_name(source['expense_name'])
        for rule in rules:
            if rule['kind']!='charge':continue
            reference='expense:'+str(source['expense_id'])
            if (name and name==normalized_name(rule['name'])) or reference in (rule.get('description') or ''):
                raise BillingValidationError('Review the existing additional charge matching "'+source['expense_name']+'" before sharing this expense. It was not charged twice.')
