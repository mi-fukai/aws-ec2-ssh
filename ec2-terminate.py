import boto3
region = 'us-west-2'

def lambda_handler(event, context):

    ec2 = boto3.client('ec2', region_name=region)

    instance_id = ec2.describe_instances(
        Filters=[{'Name':'network-interface.association.public-ip','Values':["XXX.XXX.XXX.XXX"]}]
    )["Reservations"][0]["Instances"][0]["InstanceId"]
        
    ec2.terminate_instances(InstanceIds=[instance_id])

    print('terminate your instances: ' + str(instance_id))
    
    return