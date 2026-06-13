import re

with open("payments/models.py", "r") as f:
    content = f.read()

# Models to remove
to_remove = [
    "PaymentMilestone",
    "PaymentDispute",
    "PaymentEvent",
    "PaymentCertificate",
    "PaymentDisbursement",
    "BankBeneficiary",
    "BankTransferRequest",
    "PaymentClosingStep",
    "Deal",
    "Payment",
    "EscrowAccount"
]

for model in to_remove:
    # Regex to match class definition and all its contents until the next class or end of file
    pattern = r"class " + model + r"\(models\.Model\):.*?(?=\nclass |\Z)"
    content = re.sub(pattern, "", content, flags=re.DOTALL)

with open("payments/models.py", "w") as f:
    f.write(content)

print("Cleaned models.")
