#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TEMPLATE_DIR = ROOT / "agentcore-runtime" / "PaperNotesMcp"
WORK_DIR = ROOT / ".paper-notes-local" / "agentcore-runtime" / "PaperNotesMcp"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def required(name: str) -> str:
    value = env(name)
    if not value:
        raise RuntimeError(f"Missing required value {name}. Add it to .env.")
    return value


def aws_identity(profile: str, region: str) -> dict:
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("sts").get_caller_identity()


def copy_template() -> None:
    WORK_DIR.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    shutil.copytree(
        TEMPLATE_DIR,
        WORK_DIR,
        ignore=shutil.ignore_patterns(".venv", "node_modules", "cdk.out", "*.log"),
    )


def optional_runtime_env_vars() -> list[dict[str, str]]:
    names = [
        "PAPER_NOTES_WEB_SEARCH_MAX_RESULTS",
        "PAPER_NOTES_TAVILY_SEARCH_DEPTH",
        "TAVILY_API_KEY",
        "BRAVE_SEARCH_API_KEY",
    ]
    return [{"name": name, "value": env(name)} for name in names if env(name)]


def update_runtime_config(region: str, account_id: str, knowledge_base_id: str, max_results: str) -> None:
    config_path = WORK_DIR / "agentcore" / "agentcore.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    runtime = config["runtimes"][0]
    runtime["envVars"] = [
        {"name": "AWS_REGION", "value": region},
        {"name": "PAPER_NOTES_KNOWLEDGE_BASE_ID", "value": knowledge_base_id},
        {"name": "PAPER_NOTES_KB_NUMBER_OF_RESULTS", "value": max_results or "5"},
    ] + optional_runtime_env_vars()
    config_path.write_text(f"{json.dumps(config, indent=2)}\n", encoding="utf-8")

    targets_path = WORK_DIR / "agentcore" / "aws-targets.json"
    targets = [
        {
            "name": "default",
            "description": "Default Paper Notes AgentCore deployment target",
            "account": account_id,
            "region": region,
        }
    ]
    targets_path.write_text(f"{json.dumps(targets, indent=2)}\n", encoding="utf-8")


def ensure_cdk_dependencies() -> None:
    cdk_dir = WORK_DIR / "agentcore" / "cdk"
    print("Installing AgentCore CDK dependencies in the local deploy workspace...", flush=True)
    subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund"],
        cwd=cdk_dir,
        check=True,
        text=True,
    )


def role_name_from_arn(role_arn: str) -> str:
    return role_arn.rsplit("/", 1)[-1]


def knowledge_base_arn(region: str, account_id: str, knowledge_base_id: str) -> str:
    return f"arn:aws:bedrock:{region}:{account_id}:knowledge-base/{knowledge_base_id}"


def attach_runtime_kb_policy(profile: str, region: str, account_id: str, role_arn: str, knowledge_base_id: str) -> None:
    iam = boto3.Session(profile_name=profile, region_name=region).client("iam")
    iam.put_role_policy(
        RoleName=role_name_from_arn(role_arn),
        PolicyName="PaperNotesKbRetrieve",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock:Retrieve"],
                        "Resource": knowledge_base_arn(region, account_id, knowledge_base_id),
                    }
                ],
            }
        ),
    )


def run_agentcore(args: list[str], dry_run: bool) -> tuple[int, dict | None]:
    command = ["agentcore", "deploy", "--target", "default", "-y"]
    if dry_run:
        command.append("--dry-run")
    command.extend(args)

    env_vars = os.environ.copy()
    env_vars["AWS_PROFILE"] = required("AWS_PROFILE")
    result = subprocess.run(command, cwd=WORK_DIR, env=env_vars, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    payload = None
    try:
        payload = json.loads(result.stdout)
    except Exception:
        start = result.stdout.find("{")
        end = result.stdout.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(result.stdout[start : end + 1])
            except Exception:
                payload = None
    return result.returncode, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the Paper Notes MCP server to AgentCore Runtime.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare local deploy files and show the AgentCore deployment plan.")
    parser.add_argument("--json", action="store_true", help="Forward --json to agentcore deploy.")
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    try:
        profile = required("AWS_PROFILE")
        region = required("AWS_REGION")
        knowledge_base_id = required("PAPER_NOTES_KNOWLEDGE_BASE_ID")
        max_results = env("PAPER_NOTES_KB_NUMBER_OF_RESULTS", "5")
        identity = aws_identity(profile, region)
        copy_template()
        update_runtime_config(region, str(identity["Account"]), knowledge_base_id, max_results)
    except ProfileNotFound as error:
        print(f"AWS profile was not found: {error}", file=sys.stderr)
        return 1
    except (BotoCoreError, ClientError, RuntimeError, KeyError) as error:
        print(f"Could not prepare AgentCore runtime deployment: {error}", file=sys.stderr)
        return 1

    extra_args = ["--json"]
    print(f"Prepared deploy workspace: {WORK_DIR}", flush=True)
    print("This local workspace is ignored by git, so real AWS IDs are not written to committed files.", flush=True)
    try:
        ensure_cdk_dependencies()
    except subprocess.CalledProcessError as error:
        print(f"Could not install AgentCore CDK dependencies: {error}", file=sys.stderr)
        return 1
    code, payload = run_agentcore(extra_args, args.dry_run)
    if code != 0 or args.dry_run:
        return code

    try:
        outputs = payload.get("outputs", {}) if isinstance(payload, dict) else {}
        role_arn = next(value for key, value in outputs.items() if "RoleArnOutput" in key)
        attach_runtime_kb_policy(profile, region, str(identity["Account"]), role_arn, knowledge_base_id)
        print(f"Attached PaperNotesKbRetrieve policy to runtime role {role_name_from_arn(role_arn)}.")
    except Exception as error:
        print(f"Deployment succeeded, but runtime IAM policy attachment failed: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
