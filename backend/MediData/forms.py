import os
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import Profile

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


class RegistrationForm(forms.ModelForm):
    full_name = forms.CharField(
        max_length=100,
        label="Full Name",
        widget=forms.TextInput(attrs={'placeholder': 'Enter your full name', 'class': 'form-input'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'placeholder': 'name@example.com', 'class': 'form-input'})
    )
    dob = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-input'}),
        label="Date of Birth",
        required=False
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Create password', 'class': 'form-input'}),
        min_length=6
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Confirm password', 'class': 'form-input'}),
        min_length=6
    )

    class Meta:
        model = User
        fields = ['username', 'full_name', 'email', 'dob', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Choose username', 'class': 'form-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            raise ValidationError("Passwords do not match. Please re-enter.")
        return cleaned_data


class PDFUploadForm(forms.Form):
    file = forms.FileField(
        label="Upload Medical Bill / Document",
        required=True
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data.get('file')
        if not uploaded_file:
            raise ValidationError("No file was uploaded.")

        # Check size
        if uploaded_file.size > MAX_FILE_SIZE_BYTES:
            raise ValidationError(
                f"File size exceeds the 15 MB limit (file is {uploaded_file.size / (1024 * 1024):.1f} MB)."
            )

        # Check extension
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Unsupported file format: '{ext}'. Please upload a PDF, PNG, JPG, or WEBP document."
            )

        return uploaded_file

