from django.db import migrations, models


class Migration(migrations.Migration):
    """Extra composite indexes for transaction queries."""

    dependencies = [
        ('core', '0008_userprofile_language_fix_joinrequest'),
    ]

    operations = []  # Indexes are in transactions/models.py (auto-created)
