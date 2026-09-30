from django.db import models


class Person(models.Model):
    msisdn = models.CharField(max_length=12, unique=True)
    display_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
