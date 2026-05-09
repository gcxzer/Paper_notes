#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def required(name: str, value: str) -> str:
    if not value:
        raise RuntimeError(f"Missing required value {name}. Add it to .env or pass it as an argument.")
    return value


def session(region: str) -> boto3.Session:
    profile = env("AWS_PROFILE")
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def runtime_mcp_endpoint(region: str, runtime_arn: str, qualifier: str) -> str:
    encoded_arn = quote(runtime_arn, safe="")
    return f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier={qualifier}"


def list_targets(client, gateway_id: str) -> list[dict]:
    targets: list[dict] = []
    token = None
    while True:
        kwargs = {"gatewayIdentifier": gateway_id}
        if token:
            kwargs["nextToken"] = token
        response = client.list_gateway_targets(**kwargs)
        targets.extend(response.get("items") or [])
        token = response.get("nextToken")
        if not token:
            return targets


def target_id(target: dict) -> str:
    return str(target.get("targetId") or target.get("gatewayTargetId") or "")


def role_name_from_arn(role_arn: str) -> str:
    return role_arn.rsplit("/", 1)[-1]


def attach_gateway_invoke_policy(region: str, runtime_arn: str, gateway_role_arn: str) -> None:
    profile = env("AWS_PROFILE")
    session_kwargs = {"region_name": region}
    if profile:
        session_kwargs["profile_name"] = profile
    iam = boto3.Session(**session_kwargs).client("iam")
    iam.put_role_policy(
        RoleName=role_name_from_arn(gateway_role_arn),
        PolicyName="PaperNotesInvokeMcpRuntime",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "bedrock-agentcore:InvokeAgentRuntime",
                        "Resource": [
                            runtime_arn,
                            f"{runtime_arn}/runtime-endpoint/*",
                        ],
                    }
                ],
            }
        ),
    )


def main() -> int:
    load_dotenv(ENV_PATH)
    parser = argparse.ArgumentParser(description="Create a Bedrock AgentCore Gateway MCP target for Paper Notes.")
    parser.add_argument("--gateway-id", default=env("PAPER_NOTES_AGENTCORE_GATEWAY_ID"))
    parser.add_argument("--runtime-arn", default=env("PAPER_NOTES_AGENTCORE_MCP_RUNTIME_ARN"))
    parser.add_argument("--target-name", default=env("PAPER_NOTES_GATEWAY_TARGET_NAME", "paper-notes-mcp"))
    parser.add_argument("--qualifier", default=env("PAPER_NOTES_AGENTCORE_RUNTIME_QUALIFIER", "DEFAULT"))
    parser.add_argument("--region", default=env("AWS_REGION"))
    parser.add_argument("--replace", action="store_true", help="Delete an existing target with the same name before creating it.")
    args = parser.parse_args()

    try:
        region = required("AWS_REGION", args.region)
        gateway_id = required("PAPER_NOTES_AGENTCORE_GATEWAY_ID", args.gateway_id)
        runtime_arn = required("PAPER_NOTES_AGENTCORE_MCP_RUNTIME_ARN", args.runtime_arn)
        endpoint = runtime_mcp_endpoint(region, runtime_arn, args.qualifier)
        client = session(region).client("bedrock-agentcore-control", region_name=region)

        created_new_target = False
        existing = next((item for item in list_targets(client, gateway_id) if item.get("name") == args.target_name), None)
        if existing and not args.replace:
            print(f"Target {args.target_name!r} already exists: {target_id(existing)}")
            created = existing
        elif existing:
            client.delete_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id(existing))
            print(f"Deleted existing target {args.target_name!r}: {target_id(existing)}")
            response = client.create_gateway_target(
                gatewayIdentifier=gateway_id,
                name=args.target_name,
                description="Paper Notes MCP tools hosted on AgentCore Runtime.",
                targetConfiguration={
                    "mcp": {
                        "mcpServer": {
                            "endpoint": endpoint,
                        }
                    }
                },
                credentialProviderConfigurations=[
                    {
                        "credentialProviderType": "GATEWAY_IAM_ROLE",
                        "credentialProvider": {
                            "iamCredentialProvider": {
                                "service": "bedrock-agentcore",
                                "region": region,
                            }
                        },
                    }
                ],
            )
            created = response.get("gatewayTarget") or response
            created_new_target = True
        else:
            response = client.create_gateway_target(
                gatewayIdentifier=gateway_id,
                name=args.target_name,
                description="Paper Notes MCP tools hosted on AgentCore Runtime.",
                targetConfiguration={
                    "mcp": {
                        "mcpServer": {
                            "endpoint": endpoint,
                        }
                    }
                },
                credentialProviderConfigurations=[
                    {
                        "credentialProviderType": "GATEWAY_IAM_ROLE",
                        "credentialProvider": {
                            "iamCredentialProvider": {
                                "service": "bedrock-agentcore",
                                "region": region,
                            }
                        },
                    }
                ],
            )
            created = response.get("gatewayTarget") or response
            created_new_target = True

        gateway = client.get_gateway(gatewayIdentifier=gateway_id)
        gateway_role_arn = gateway.get("roleArn") or gateway.get("gateway", {}).get("roleArn")
        if gateway_role_arn:
            attach_gateway_invoke_policy(region, runtime_arn, str(gateway_role_arn))
            print(f"Attached PaperNotesInvokeMcpRuntime policy to gateway role {role_name_from_arn(str(gateway_role_arn))}.")
        client.synchronize_gateway_targets(gatewayIdentifier=gateway_id, targetIdList=[target_id(created)])
    except ProfileNotFound as error:
        print(f"AWS profile was not found: {error}", file=sys.stderr)
        return 1
    except (BotoCoreError, ClientError, RuntimeError) as error:
        print(f"Could not create AgentCore MCP target: {error}", file=sys.stderr)
        return 1

    verb = "Created" if created_new_target else "Configured existing"
    print(f"{verb} target {created.get('name', args.target_name)!r}: {target_id(created)}")
    print(f"MCP endpoint: {endpoint}")
    print("Gateway target synchronization started. Wait for the target status to become READY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
