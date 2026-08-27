from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm
from .models import Product, Customer, LeaveApplication, UploadedFile, Employee


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'quantity', 'price']


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'email', 'phone', 'address']


class LeaveApplicationForm(forms.ModelForm):
    class Meta:
        model = LeaveApplication
        fields = ['start_date', 'end_date', 'reason']  # 🔥 REMOVE leave_type


class UploadedFileForm(forms.ModelForm):
    class Meta:
        model = UploadedFile
        fields = ['file']


class FileUploadForm(forms.ModelForm):
    class Meta:
        model = UploadedFile
        fields = ['file']


class UserProfileForm(forms.ModelForm):
    """Form for editing Django User model fields"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'First Name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'Last Name'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'Email Address'
            }),
        }


class EmployeeProfileForm(forms.ModelForm):
    """Form for editing Employee model fields"""
    class Meta:
        model = Employee
        fields = ['phone', 'position', 'department', 'employee_id', 'location', 'bio', 'profile_photo']
        widgets = {
            'phone': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'Phone Number'
            }),
            'position': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'Job Title/Position'
            }),
            'department': forms.Select(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none'
            }),
            'employee_id': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'Employee ID',
                'readonly': 'readonly'
            }),
            'location': forms.TextInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'Location/Office'
            }),
            'bio': forms.Textarea(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'placeholder': 'About you (bio)',
                'rows': 4
            }),
            'profile_photo': forms.FileInput(attrs={
                'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
                'accept': 'image/*'
            }),
        }


class CustomPasswordChangeForm(PasswordChangeForm):
    """Custom password change form with Tailwind styling"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['old_password'].widget.attrs.update({
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
            'placeholder': 'Current Password'
        })
        self.fields['new_password1'].widget.attrs.update({
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
            'placeholder': 'New Password'
        })
        self.fields['new_password2'].widget.attrs.update({
            'class': 'w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 focus:outline-none',
            'placeholder': 'Confirm New Password'
        })