import boto3
from botocore.client import Config
from .config import get_settings

class ObjectStorage:
    def __init__(self):
        s=get_settings(); endpoint=('https://' if s.minio_secure else 'http://')+s.minio_endpoint
        self.client=boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=s.minio_access_key, aws_secret_access_key=s.minio_secret_key, config=Config(signature_version='s3v4'))
        self.bucket=s.minio_bucket
        try: self.client.head_bucket(Bucket=self.bucket)
        except Exception: self.client.create_bucket(Bucket=self.bucket)
    def put(self, key, data, content_type):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
    def get(self,key):
        return self.client.get_object(Bucket=self.bucket,Key=key)['Body'].read()
    def delete(self,key):
        self.client.delete_object(Bucket=self.bucket,Key=key)
