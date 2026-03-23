#!/bin/bash

if [[ -z "$1" && -z "$2" && -z "$3" ]]; then
  echo "Usage: create.sh <project-type> [project-name] [project-path]"
  exit 1
fi

VALID_PROEJCT_TYPES=("maven")

PROJECT_TYPE=$1
PROJECT_NAME=$2
PROJECT_PATH=$3
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TEMPLATE_DIR="${SCRIPT_DIR}/templates/${PROJECT_TYPE}/"

if [[ ! " ${VALID_PROEJCT_TYPES[@]} " =~ " ${PROJECT_TYPE} " ]]; then
  echo "Invalid project type. Valid project types are: ${VALID_PROEJCT_TYPES[@]}"
  exit 1
fi

if [[ -z "$PROJECT_NAME" ]]; then
  GIT_ROOT=$(git rev-parse --show-toplevel)
  if [[ -z "${GIT_ROOT}" || ! -d "${GIT_ROOT}" ]]; then
    echo "Project name is required. when not running from a git repository."
    exit 1
  fi
  PROJECT_NAME=$(basename "${GIT_ROOT}" | sed 's|^apx-||g')
  PROJECT_PATH="${GIT_ROOT}"
fi

trap 'echo "failed to setup project. you may need to run git clean -ffdx before re-running"; exit 1' ERR

if [[ -z "$PROJECT_PATH" ]]; then
  echo "Project path is required."
  exit 1
elif [[ -d "$PROJECT_PATH" ]]; then
  echo "Project path already exists: $PROJECT_PATH"
elif [[ -f "$PROJECT_PATH" ]]; then
  echo "Invalid project path. Project path is a file."
  exit 1
elif [[ ! -e "$PROJECT_PATH" ]]; then
  echo "Creating project path: $PROJECT_PATH"
  mkdir -p $PROJECT_PATH
fi

if [[ "$(ls -1 "${PROJECT_PATH}" | wc -l )" -ne 0 ]];then
  read -p "Project path ${PROJECT_PATH} is not empty. Do you want to continue? (Y/N): " choice
  if [[ $choice == "Y" || $choice == "y" ]]; then
    echo "Continuing..."
  else
    echo "Aborted."
    exit 1
  fi
fi

echo "copying project template over"
cp -a "${TEMPLATE_DIR}" "${PROJECT_PATH}/"

maven_setup() {
  echo "replacing project name in files"
  find "${PROJECT_PATH}" -type f | xargs gsed -i "s|PROJECTNAME|${PROJECT_NAME}|g";
  PROJECT_NAME_CAMEL=$(echo "$PROJECT_NAME" | gsed -r 's/-(.)/\U\1/g')
  find "${PROJECT_PATH}" -type f | xargs gsed -i "s|example|${PROJECT_NAME_CAMEL}|g";
  
  echo "renaming files"
  for file in $(find "${PROJECT_PATH}" -name '*example*' | sort -r); do
    mv $file $(dirname $file)/$(basename $file | sed "s|example|${PROJECT_NAME_CAMEL}|g")
  done
}

case $PROJECT_TYPE in
  maven)
    maven_setup
    ;;
  *)
    echo "Invalid project type. Valid project types are: ${VALID_PROEJCT_TYPES[@]}"
    exit 1
    ;;
esac

echo "doing cleanup"
rm -rf "${PROJECT_PATH}/templates"
rm -f "${PROJECT_PATH}/init.sh"

echo "setup completed"