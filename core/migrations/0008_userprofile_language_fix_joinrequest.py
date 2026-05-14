from django.db import migrations, models
import core.models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_family_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='language',
            field=models.CharField(
                choices=[('uz', "O'zbek"), ('ru', 'Русский'), ('en', 'English')],
                default='uz',
                max_length=5,
            ),
        ),
        migrations.AlterField(
            model_name='userprofile',
            name='avatar',
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=core.models.avatar_upload_path,
            ),
        ),
        migrations.AlterUniqueTogether(
            name='familyjoinrequest',
            unique_together=set(),
        ),
        migrations.AddIndex(
            model_name='familyjoinrequest',
            index=models.Index(fields=['family', 'status'], name='core_familyjoinrequest_family_status_idx'),
        ),
        migrations.AddIndex(
            model_name='familyjoinrequest',
            index=models.Index(fields=['user', 'status'], name='core_familyjoinrequest_user_status_idx'),
        ),
    ]
