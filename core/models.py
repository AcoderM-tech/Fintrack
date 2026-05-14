from django.db import models
from django.contrib.auth.models import User
import os


def avatar_upload_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"avatars/user_{instance.user_id}{ext}"


class FamilyGroup(models.Model):
    name = models.CharField(max_length=100, verbose_name="Guruh nomi")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_groups')
    members = models.ManyToManyField(User, through='FamilyMember', related_name='family_groups', blank=True)
    invite_code = models.CharField(max_length=20, unique=True, blank=True)
    invite_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.invite_code:
            import random, string
            self.invite_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Oila guruhi"
        verbose_name_plural = "Oila guruhlari"


class FamilyMember(models.Model):
    ROLE_CHOICES = [
        ('father', 'Ota'),
        ('mother', 'Ona'),
        ('son', "O'g'il"),
        ('daughter', 'Qiz'),
    ]
    family = models.ForeignKey(FamilyGroup, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='family_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='father')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('family', 'user')
        verbose_name = "Oila a'zosi"
        verbose_name_plural = "Oila a'zolari"
        indexes = [
            models.Index(fields=['user', 'family']),
            models.Index(fields=['family', 'role']),
            models.Index(fields=['user', 'role']),
        ]

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class FamilyJoinRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Kutilmoqda'),
        ('approved', 'Tasdiqlandi'),
        ('rejected', 'Rad etildi'),
    ]
    family = models.ForeignKey(FamilyGroup, on_delete=models.CASCADE, related_name='join_requests')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='family_join_requests')
    role = models.CharField(max_length=20, choices=FamilyMember.ROLE_CHOICES, default='son')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Oila qo'shilish so'rovi"
        verbose_name_plural = "Oila qo'shilish so'rovlari"
        # FIX: unique_together dan olib tashlandi — rejected keyin qayta so'rov yuboriladi
        indexes = [
            models.Index(fields=['family', 'status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.user.username} -> {self.family.name} ({self.status})"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    GENDER_CHOICES = [
        ('male', 'Erkak'),
        ('female', 'Ayol'),
    ]
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, null=True, blank=True)
    LANGUAGE_CHOICES = [
        ('uz', "O'zbek"),
        ('ru', 'Русский'),
        ('en', 'English'),
    ]
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='uz')
    default_currency = models.CharField(max_length=3, default='UZS', choices=[
        ('UZS', "O'zbek so'mi"),
        ('USD', 'Dollar'),
        ('EUR', 'Yevro'),
        ('RUB', 'Rubl'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} profili"

    def get_avatar_url(self):
        if self.avatar:
            return self.avatar.url
        return None

    class Meta:
        verbose_name = "Foydalanuvchi profili"
        verbose_name_plural = "Foydalanuvchi profillari"


class Notification(models.Model):
    LEVEL_CHOICES = [
        ('info', 'Info'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('danger', 'Danger'),
    ]
    TYPE_CHOICES = [
        ('budget_exceeded', 'Budget Exceeded'),
        ('spending_spike', 'Spending Spike'),
        ('low_balance', 'Low Balance'),
        ('debt_due', 'Debt Due Soon'),
        ('other', 'Other'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    family = models.ForeignKey(FamilyGroup, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')
    notif_type = models.CharField(max_length=40, choices=TYPE_CHOICES, default='other')
    title = models.CharField(max_length=200)
    message = models.TextField()
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='info')
    key = models.CharField(max_length=120, blank=True, db_index=True)
    related_object_type = models.CharField(max_length=50, blank=True)
    related_object_id = models.PositiveIntegerField(null=True, blank=True)
    data = models.JSONField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}: {self.title}"

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']
