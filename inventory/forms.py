from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm
from django.db import transaction
from django.db.models import F, Q, Sum
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.forms import inlineformset_factory
from pathlib import Path
from .models import Product, Customer, LeaveApplication, UploadedFile, Employee, Order, OrderItem, Payment


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

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'The end date must be on or after the start date.')
        return cleaned_data


class UploadedFileForm(forms.ModelForm):
    class Meta:
        model = UploadedFile
        fields = ['file']


class FileUploadForm(forms.ModelForm):
    class Meta:
        model = UploadedFile
        fields = ['file']
        widgets = {
            'file': forms.ClearableFileInput(attrs={
                'accept': '.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.png,.jpg,.jpeg',
            }),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data['file']
        allowed_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.png', '.jpg', '.jpeg'}
        extension = Path(uploaded_file.name).suffix.lower()
        if extension not in allowed_extensions:
            raise forms.ValidationError(
                'Upload a PDF, Word, Excel, CSV, text, or image document.'
            )
        if uploaded_file.size > 20 * 1024 * 1024:
            raise forms.ValidationError('Files must be 20 MB or smaller.')
        return uploaded_file


class OrderChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, order):
        recorded = order.recorded_payments or 0
        balance = order.total_amount - recorded
        return f"Order #{order.pk} — {order.customer.name} • Remaining: ₹{balance:,.2f}"


class PaymentForm(forms.ModelForm):
    PAYMENT_METHOD_CHOICES = (
        ('Cash', 'Cash'),
        ('UPI', 'UPI'),
        ('Card', 'Credit / debit card'),
        ('Bank transfer', 'Bank transfer'),
        ('Cheque', 'Cheque'),
        ('Other', 'Other'),
    )

    order = OrderChoiceField(
        queryset=Order.objects.none(),
        label='Order',
        widget=forms.Select(attrs={'data-payment-order': 'true'}),
    )
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
    )
    payment_method = forms.ChoiceField(choices=PAYMENT_METHOD_CHOICES)
    other_payment_method = forms.CharField(
        max_length=50,
        required=False,
        label='Specify payment method',
        widget=forms.TextInput(attrs={'placeholder': 'Enter payment method'}),
    )

    class Meta:
        model = Payment
        fields = ['order', 'amount', 'payment_method', 'other_payment_method']
        widgets = {
            'order': forms.Select(),
            'payment_method': forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].help_text = "Choose the customer order this payment is for."
        self.fields["amount"].label = "Amount received"
        self.fields["amount"].help_text = "Enter a full or partial amount already received."
        self.fields["payment_method"].label = "How did the customer pay?"
        self.fields["other_payment_method"].label = "Other payment method"
        self.fields['order'].queryset = (
            Order.objects.select_related('customer')
            .annotate(recorded_payments=Sum('payment__amount'))
            .filter(Q(recorded_payments__isnull=True) | Q(total_amount__gt=F('recorded_payments')))
            .order_by('-date', '-pk')
        )
        self.fields['order'].widget.choices = [
            ("", "Choose an order")
        ] + [
            (
                order.pk,
                self.fields['order'].label_from_instance(order),
            )
            for order in self.fields['order'].queryset
        ]

    def clean_payment_method(self):
        return self.cleaned_data['payment_method'].strip()

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('payment_method')
        other_method = cleaned_data.get('other_payment_method', '').strip()
        if method == 'Other':
            if not other_method:
                self.add_error('other_payment_method', 'Enter the payment method used.')
            else:
                cleaned_data['payment_method'] = other_method
        elif other_method:
            self.add_error(
                'other_payment_method',
                'Choose “Other” before entering a custom payment method.',
            )

        order = cleaned_data.get('order')
        amount = cleaned_data.get('amount')
        if order and amount:
            paid_amount = (
                Payment.objects.filter(order=order).aggregate(total=Sum('amount'))['total'] or 0
            )
            if amount > order.total_amount - paid_amount:
                self.add_error(
                    'amount',
                    "The payment cannot exceed the order's remaining balance.",
                )
        return cleaned_data


class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ["customer"]


class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ["product", "quantity"]
        widgets = {
            "product": forms.Select(attrs={"class": "order-product"}),
            "quantity": forms.NumberInput(attrs={"min": "1", "step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.order_by("name")

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity < 1:
            raise forms.ValidationError("Enter a quantity of at least 1.")
        product = self.cleaned_data.get("product")
        if product and quantity > product.quantity:
            raise forms.ValidationError(
                f"Only {product.quantity} units are currently in stock."
            )
        return quantity


class OrderItemFormSetBase(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        selected_products = []
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get("DELETE"):
                product = form.cleaned_data.get("product")
                if product:
                    selected_products.append(product.pk)

        if not selected_products:
            raise ValidationError("Add at least one product to this order.")
        if len(selected_products) != len(set(selected_products)):
            raise ValidationError(
                "Each product can appear only once. Increase its quantity on one line."
            )


OrderItemFormSet = inlineformset_factory(
    Order,
    OrderItem,
    form=OrderItemForm,
    formset=OrderItemFormSetBase,
    extra=1,
    can_delete=True,
)


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