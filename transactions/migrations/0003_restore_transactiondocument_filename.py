# Generated to repair missing filename column on TransactionDocument.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("transactions", "0002_transaction_created_by_alter_transaction_stage_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                """
                ALTER TABLE transactions_transactiondocument
                ADD COLUMN IF NOT EXISTS filename varchar(255);
                """,
                """
                UPDATE transactions_transactiondocument
                SET filename = COALESCE(
                    NULLIF(filename, ''),
                    COALESCE(regexp_replace("file"::text, '^.*/', ''), '')
                )
                WHERE filename IS NULL OR filename = '';
                """,
                """
                ALTER TABLE transactions_transactiondocument
                ALTER COLUMN filename SET NOT NULL;
                """,
            ],
            reverse_sql=[
                """
                ALTER TABLE transactions_transactiondocument
                DROP COLUMN IF EXISTS filename;
                """
            ],
        ),
    ]
