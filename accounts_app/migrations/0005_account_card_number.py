
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts_app', '0004_account_family'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='card_number',
            field=models.CharField(blank=True, max_length=19, verbose_name='Karta raqami'),
        ),
    ]
