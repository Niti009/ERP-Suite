from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
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


class EmployeeCreateForm(forms.Form):
    first_name = forms.CharField(max_length=50, required=True)
    last_name = forms.CharField(max_length=50, required=True)
    username = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    phone = forms.CharField(max_length=20, required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    gender = forms.ChoiceField(choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')], required=False)
    address = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    location = forms.CharField(max_length=100, required=False)
    employee_id = forms.CharField(max_length=20, required=True)
    department = forms.ModelChoiceField(queryset=Employee._meta.get_field('department').remote_field.model.objects.all(), required=False, empty_label='Select department')
    position = forms.CharField(max_length=100, required=True)
    joining_date = forms.DateField(required=True, widget=forms.DateInput(attrs={'type': 'date'}))
    employment_status = forms.ChoiceField(choices=[('Active', 'Active'), ('Inactive', 'Inactive')], initial='Active')
    profile_photo = forms.ImageField(required=False)

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop('instance', None)
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            if isinstance(field, forms.BooleanField):
                field.widget.attrs.update({'class': 'h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500'})
            elif isinstance(field, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs.update({'class': 'w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20'})
            elif isinstance(field, forms.FileInput):
                field.widget.attrs.update({'class': 'block w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-700 shadow-sm file:mr-4 file:rounded-lg file:border-0 file:bg-indigo-600 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white'})
            elif isinstance(field, forms.Textarea):
                field.widget.attrs.update({'class': 'w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20'})
            else:
                field.widget.attrs.update({'class': 'w-full rounded-xl border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20'})

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        existing_user = User.objects.filter(username__iexact=username).first()
        if existing_user and (not self.instance or existing_user.pk != self.instance.user_id):
            raise forms.ValidationError('A user with this username already exists.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user and (not self.instance or existing_user.pk != self.instance.user_id):
            raise forms.ValidationError('A user with this email already exists.')
        return email

    def clean_employee_id(self):
        employee_id = self.cleaned_data.get('employee_id', '').strip()
        existing_employee = Employee.objects.filter(employee_id__iexact=employee_id).first()
        if existing_employee and (not self.instance or existing_employee.pk != self.instance.pk):
            raise forms.ValidationError('This employee ID already exists.')
        return employee_id

    def clean(self):
        return super().clean()

    def save(self):
        with transaction.atomic():
            user = User.objects.create_user(
                username=self.cleaned_data['username'].strip(),
                first_name=self.cleaned_data['first_name'].strip(),
                last_name=self.cleaned_data['last_name'].strip(),
                email=self.cleaned_data['email'].strip(),
                password=None,
                is_active=False,
            )

            employee, _ = Employee.objects.get_or_create(
                user=user,
                defaults={
                    'name': user.get_full_name().strip() or user.username,
                    'position': self.cleaned_data['position'],
                    'salary': 0.00,
                    'joining_date': self.cleaned_data['joining_date'],
                },
            )
            employee.name = user.get_full_name().strip() or user.username
            employee.phone = self.cleaned_data.get('phone', '')
            employee.date_of_birth = self.cleaned_data.get('date_of_birth')
            employee.gender = self.cleaned_data.get('gender', '')
            employee.position = self.cleaned_data['position']
            employee.employment_status = self.cleaned_data['employment_status']
            employee.department = self.cleaned_data.get('department')
            employee.salary = 0.00
            employee.joining_date = self.cleaned_data['joining_date']
            employee.employee_id = self.cleaned_data['employee_id']
            employee.location = self.cleaned_data.get('location', '')
            employee.bio = self.cleaned_data.get('address', '')
            employee.profile_photo = self.cleaned_data.get('profile_photo')
            employee.save()
        return user, employee


class EmployeePromptForm(forms.Form):
    title = forms.CharField(max_length=200, label="Subject")
    message = forms.CharField(
        max_length=3000,
        label="Message or request",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def clean_title(self):
        return self.cleaned_data["title"].strip()

    def clean_message(self):
        return self.cleaned_data["message"].strip()


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