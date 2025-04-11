#!/bin/bash
# git update-index --chmod=+x docker_scripts.sh

# Get passed arguments
ACTION=$1
APPLICATION=$2
DOCKER_IMAGE_NAME=${3:-$APPLICATION}

# Get environment variables
PYTHON_ENV=${PYTHON_ENV:=development}
BRANCH_NAME=${BRANCH_NAME:=development}
LOCAL_REPO=${LOCAL_REPO:=dockerrepo.softdesign.dk:5000}
PYTHON_VERSION=${PYTHON_VERSION:=3.13}
# --

# Identify the hostname
HOST_NAME=`hostname`
# --

# Identify the home directory of this script file - SCRIPT_DIR 
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE" # if $SOURCE was a relative symlink, we need to resolve it relative to the path where the symlink file was located
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" && pwd )"
# --

# Setup home directory - root
HOME_DIR=$SCRIPT_DIR/..
# --

# Check if Jenkins IMG_VERSION is available if so use it - if not set IMG_VERSION defaults to 0 (zero)
JENKINS=0
IMG_VERSION="${IMG_VERSION:-0}"
# -- 

# Get the VERSION number from the VERSION file only if jenkins IMG_VERSION is not supplied
if [ $IMG_VERSION -eq 0 ]; then
  # Get current docker image version
  if [[ ! -e $SCRIPT_DIR/VERSION ]]; then
    echo 1 >$SCRIPT_DIR/VERSION
  fi
  VERSION=`cat $SCRIPT_DIR/VERSION`
else
  JENKINS=1
  VERSION=$IMG_VERSION
fi
# --

# Print out configuration
echo "APPLICATION..........: $APPLICATION"
echo "ACTION...............: $ACTION"
echo "HOST_NAME............: $HOST_NAME"
echo "PYTHON_ENV...........: $PYTHON_ENV"
echo "SCRIPT_DIR...........: $SCRIPT_DIR"
echo "HOME_DIR.............: $HOME_DIR"
echo "VERSION..............: $VERSION"
echo "JENKINS..............: $JENKINS"
echo "BRANCH_NAME..........: $BRANCH_NAME"
echo "PYTHON_VERSION.......: $PYTHON_VERSION"
echo "LOCAL_REPO...........: $LOCAL_REPO"
echo "DOCKER_IMAGE_NAME....: $DOCKER_IMAGE_NAME"

TAG_BUILD=${LOCAL_REPO}/$DOCKER_IMAGE_NAME-${BRANCH_NAME}:build
TAG_DEPLOY=${LOCAL_REPO}/$DOCKER_IMAGE_NAME-${BRANCH_NAME}:${VERSION}
TAG_DEPLOY_LATEST=${LOCAL_REPO}/$DOCKER_IMAGE_NAME-${BRANCH_NAME}:latest

# Ensure HOME_DIR is the current folder (location of Dockerfile)
pushd $HOME_DIR > /dev/null
# --

case $ACTION in
    "build") 
        # If JENKINS is 0 we will increment the VERSION number and store it in the VERSIONs file
        # otherwise the VERSION will include the IMG_VERSION as supplied by Jenkins
        if [ $JENKINS -eq 0 ]; then
          VERSION=$(($VERSION +1))
          echo $VERSION >$SCRIPT_DIR/VERSION
        fi

        echo "Building docker image for build ${DOCKER_IMAGE_NAME} version ${VERSION}"

        # Build docker image
        docker build \
          --target build \
          --build-arg PYTHON_VERSION=${PYTHON_VERSION} \
          --build-arg LOCAL_REPO=${LOCAL_REPO} \
          --build-arg APPLICATION=${APPLICATION} \
          --build-arg BRANCH=${BRANCH_NAME} \
          -t ${TAG_BUILD} \
          -f apps/${APPLICATION}/Dockerfile .

        exitCode=$?;;

    "test") 
        echo "Run tests and provide test coverage / results in .reports folder"

        # Ensure the reports folder is available for the dockerfile to provide reports
        mkdir -p ${HOME_DIR}/temp

        # Run the tests inside docker container
        docker run \
          --rm \
          -v ${HOME_DIR}/temp:/app/.reports \
           ${TAG_BUILD} bash -c "uv run pytest --junitxml=/app/.reports/test-results.xml"

        exitCode=$?;;

    "build-prod") 
        echo "Building docker image ${DOCKER_IMAGE_NAME} version ${VERSION}"
        echo "PYTHON_ENV..........: $PYTHON_ENV"

        # Build docker image
        docker build \
          --build-arg PYTHON_VERSION=${PYTHON_VERSION} \
          --build-arg LOCAL_REPO=${LOCAL_REPO} \
          --build-arg APPLICATION=${APPLICATION} \
          --build-arg BRANCH=${BRANCH_NAME} \
          --build-arg BUILD_DATE="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
          -t ${TAG_DEPLOY_LATEST} \
          -t ${TAG_DEPLOY} \
          -f apps/${APPLICATION}/Dockerfile .

        exitCode=$?;;

    "repo-push")
        docker image push --quiet --all-tags ${LOCAL_REPO}/$DOCKER_IMAGE_NAME-${BRANCH_NAME}
        exitCode=$?;;

    *)
      echo "Unknown action provided supported actions are run, start, stop or remove!"
      exitCode=999;;
esac

popd > /dev/null

exit $exitCode