#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

MEMORY_ACTIONS = [
    "bedrock-agentcore:ListEvents",
    "bedrock-agentcore:CreateEvent",
    "bedrock-agentcore:GetEvent",
    "bedrock-agentcore:ListSessions",
    "bedrock-agentcore:RetrieveMemoryRecords",
    "bedrock-agentcore:ListMemoryRecords",
    "bedrock-agentcore:GetMemoryRecord",
]


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def required(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing required value {name}. Add it to .env.")
    return value


def session(region: str) -> boto3.Session:
    profile = env("AWS_PROFILE")
    if profile:
        return boto3.Session(profile_name=profile, region_name=region)
    return boto3.Session(region_name=region)


def harness_id_from_value(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def role_name_from_arn(role_arn: str) -> str:
    return role_arn.rsplit("/", 1)[-1]


def configured_memory_arn(harness: dict) -> str:
    direct_arn = env("PAPER_NOTES_MEMORY_ARN")
    if direct_arn:
        return direct_arn
    memory_config = harness.get("memory") or {}
    agentcore_memory = memory_config.get("agentCoreMemoryConfiguration") or {}
    return str(agentcore_memory.get("arn") or "").strip()


def policy_document(memory_arn: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PaperNotesAgentCoreMemoryAccess",
                    "Effect": "Allow",
                    "Action": MEMORY_ACTIONS,
                    "Resource": [memory_arn, f"{memory_arn}/*"],
                }
            ],
        }
    )


def main() -> int:
    if not ENV_PATH.exists():
        print("Missing .env. Create it with: cp .env.example .env", file=sys.stderr)
        return 1

    load_dotenv(ENV_PATH)
    try:
        region = required("AWS_REGION")
        harness_id = harness_id_from_value(required("PAPER_NOTES_AGENTCORE_HARNESS_ARN"))
        if not re.match(r"^[A-Za-z0-9_.:/-]+$", harness_id):
            raise RuntimeError("PAPER_NOTES_AGENTCORE_HARNESS_ARN does not look like a valid Harness ARN or ID.")

        aws_session = session(region)
        control = aws_session.client("bedrock-agentcore-control", region_name=region)
        harness = control.get_harness(harnessId=harness_id).get("harness") or {}
        role_arn = str(harness.get("executionRoleArn") or "").strip()
        memory_arn = configured_memory_arn(harness)
        if not role_arn:
            raise RuntimeError("Harness executionRoleArn was not returned by GetHarness.")
        if not memory_arn:
            raise RuntimeError(
                "No Memory ARN found. Attach Memory to the Harness or set PAPER_NOTES_MEMORY_ARN in .env."
            )

        iam = aws_session.client("iam")
        role_name = role_name_from_arn(role_arn)
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="PaperNotesMemoryAccess",
            PolicyDocument=policy_document(memory_arn),
        )
    except ProfileNotFound as error:
        print(f"AWS profile was not found: {error}", file=sys.stderr)
        return 1
    except (BotoCoreError, ClientError, RuntimeError) as error:
        print(f"Could not attach Harness Memory policy: {error}", file=sys.stderr)
        return 1

    print(f"Attached PaperNotesMemoryAccess to Harness role {role_name}.")
    print(f"Memory ARN: {memory_arn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
