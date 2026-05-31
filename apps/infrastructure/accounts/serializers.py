from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import CustomUser


class MinimalOrgSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    subdomain = serializers.CharField()
    subscription_status = serializers.CharField()
    plan_tier = serializers.CharField()


class UserProfileSerializer(serializers.ModelSerializer):
    org = MinimalOrgSerializer(read_only=True)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = CustomUser
        fields = ["id", "email", "role", "org", "full_name", "phone"]
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(
            request=self.context.get("request"),
            username=data["email"],
            password=data["password"],
        )
        if not user:
            raise serializers.ValidationError("Invalid credentials.")
        if not user.is_active:
            raise serializers.ValidationError("Account is inactive.")
        data["user"] = user
        return data


class TokenResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserProfileSerializer()


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        request = self.context["request"]
        if not request.user.check_password(data["old_password"]):
            raise serializers.ValidationError({"old_password": "Incorrect password."})
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data


class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ["email", "first_name", "last_name", "phone", "role"]

    def validate_role(self, value):
        if value == "super_admin":
            raise serializers.ValidationError("Cannot assign super_admin role.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        import secrets
        temp_password = secrets.token_urlsafe(12)
        user = CustomUser.objects.create_user(
            email=validated_data["email"],
            username=validated_data["email"],
            password=temp_password,
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            phone=validated_data.get("phone", ""),
            role=validated_data["role"],
            org=request.user.org,
        )
        user._temp_password = temp_password
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = "email"

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["org_id"] = str(user.org_id) if user.org_id else None
        token["role"] = user.role
        token["full_name"] = user.full_name
        return token
