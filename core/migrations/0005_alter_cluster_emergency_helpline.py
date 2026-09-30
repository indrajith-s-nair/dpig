from django.db import migrations, models


def update_helpline_and_broadcasts(apps, schema_editor):
    Cluster = apps.get_model('core', 'Cluster')
    Cluster.objects.filter(emergency_helpline='1913').update(emergency_helpline='1234')
    Cluster.objects.filter(emergency_helpline='').update(emergency_helpline='1234')
    Cluster.objects.filter(emergency_helpline__isnull=True).update(emergency_helpline='1234')

    GovernmentBroadcast = apps.get_model('core', 'GovernmentBroadcast')
    for b in GovernmentBroadcast.objects.filter(content__contains='1913'):
        b.content = b.content.replace('1913', '1234')
        b.save(update_fields=['content'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_aadhaarverificationrecord_complaint_aadhaar_last4_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cluster',
            name='emergency_helpline',
            field=models.CharField(default='1234', max_length=50),
        ),
        migrations.RunPython(update_helpline_and_broadcasts, reverse_code=migrations.RunPython.noop),
    ]
