from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, trim_whitespace=True)
    finish = serializers.CharField(max_length=200, trim_whitespace=True)
    include_geometry = serializers.BooleanField(default=True, required=False)
