# couchbase_upgrade

Performs a rolling upgrade of an Couchbase cluster. It's great for keeping your cluster automatically
patched without downtime.

Nodes that already have the correct version are skipped. So the script can be executed multiple times if desired. 

# Usage

    usage: couchbase_upgrade.py [-h] -n NODES -u USERNAME -P PASSWORD [-p PORT]
                                [--cli CLI]
                                [--service-stop-command SERVICE_STOP_COMMAND]
                                [--service-start-command SERVICE_START_COMMAND]
                                [--upgrade-command UPGRADE_COMMAND]
                                [--latest-version-command LATEST_VERSION_COMMAND]
                                [--version VERSION]
                                [--upgrade-system-command UPGRADE_SYSTEM_COMMAND]
                                [--upgrade-system] [--reboot] [--force-reboot]
                                [-v]
    
    Performs a rolling upgrade of a Couchbase cluster
    
    optional arguments:
      -h, --help            show this help message and exit
      -n NODES, --nodes NODES
                            Comma separated list of host names or IP addresses of
                            nodes
      -u USERNAME, --username USERNAME
                            Username for authentication
      -P PASSWORD, --password PASSWORD
                            Password for authentication
      -p PORT, --port PORT  Couchbase HTTP port. Default 8091
      --cli CLI             Shell command to the Couchbase CLI. Default 'sudo
                            /opt/couchbase/bin/couchbase-cli'
      --service-stop-command SERVICE_STOP_COMMAND
                            Shell command to stop the Couchbase service on a node.
                            Default 'sudo systemctl stop couchbase-server'
      --service-start-command SERVICE_START_COMMAND
                            Shell command to start the Couchbase service on a
                            node. Default 'sudo systemctl start couchbase-server'
      --upgrade-command UPGRADE_COMMAND
                            Command to upgrade Couchbase on a node. Default 'sudo
                            yum clean all && sudo yum install -y couchbase-server-
                            community'
      --latest-version-command LATEST_VERSION_COMMAND
                            Command to get the latest version in the repository.
                            Default "sudo yum clean all >/dev/null 2>&1 && sudo
                            yum list all couchbase-server-community | grep
                            couchbase-server-community | awk '{ print $2 }' | cut
                            -d '-' -f1 | sort --version-sort -r | head -n 1"
      --version VERSION     A specific version to upgrade to or 'latest'. If
                            'latest', then the highest available version in the
                            repository will be determined. Nodes with a version
                            equal or higher will be skipped. Default 'latest'
      --upgrade-system-command UPGRADE_SYSTEM_COMMAND
                            Command to upgrade operating system. Default 'sudo yum
                            clean all && sudo yum update -y'
      --upgrade-system      Upgrades the operating system also after upgrading
                            Couchbase
      --reboot              Reboots the server if an actual upgrade took place
      --force-reboot        Always reboots the server, even though no upgrade
                            occurred because the version was already the latest
      -v, --verbose         Display of more information

Only the nodes parameter is required. This script works by default with a YUM installation
of Couchbase. But with the command parameters it can be configured for other operating
systems as well. It should also work with archive (tar) based installations.

**As root user**:

    ./couchbase_upgrade.py --nodes host1,host2,host3
                
**As non-root user with restrictive sudo rights**:

    ./couchbase_upgrade.py\
     --nodes host1,host2,host3\
     --service-stop-command 'sudo /usr/local/bin/couchbasectl service stop couchbase'\
     --service-start-command 'sudo /usr/local/bin/couchbasectl service start couchbase'\
     --upgrade-command 'sudo /usr/local/bin/couchbasectl update'\
     --latest-version-command 'sudo /usr/local/bin/couchbasectl latest-version'

# Restrictive sudo rights

The upgrade script requires several actions that must be executed as root. But it would be
better to let a non-root user execute the upgrade script with restrictive sudo rights. A nice way
to do that is with sudo line and script below. 

**/etc/sudoers.d/couchbasectl**

    # Allow myuser to use couchbasectl that can stop/start/restart the couchbase service
    myuser ALL=(root) NOPASSWD: /usr/local/bin/couchbasectl

**/usr/local/bin/couchbasectl**

    #!/bin/bash
    
    # Couchbase ctl
    # This file exists to perform limited actions with sudo
    
    if [ "$1" == "service" ]; then
      if [ "$2" != 'start' ] && [ "$2" != 'stop' ] && [ "$2" != 'restart' ]; then
        echo 'Service sub command must be start, stop or restart'
        exit 1
      fi
    
      # Check if service name is empty
      if [[ -z "$3" ]]; then
        echo 'Service name must be specified'
        exit 1
      fi
    
      # Check if service name starts with "couchbase"
      if [[ "$3" != "couchbase"* ]]; then
        echo 'Service name must start with couchbase'
        exit 1
      fi
    
      systemctl $2 $3
    elif [ "$1" == "latest-version" ]; then
      sudo yum clean all >/dev/null 2>&1 &&
      yum list all couchbase-server-community | grep couchbase-server-community | awk '{ print $2 }' |
      cut -d '-' -f1 | sort --version-sort -r | head -n 1
    elif [ "$1" == "update" ]; then
      sudo yum clean all && sudo yum install -y couchbase-server-community
    elif [[ ! -z "$1" ]] ; then
      echo 'This sub command is not allowed'
      exit 1
    else
      echo 'Usage:'
      echo "./couchbasectl service (start|stop|restart) couchbase-server"
      echo "./couchbasectl latest-version"
      echo "./couchbasectl update"
    fi

# Disable SSH strict host key checking

If you have a trusted environment, you can disable strict host key checking to avoid having to type "yes"
for a SSH connection to each node. However, keep in mind that this could be a security risk.

Add to the ~/.ssh/config file of the user how executes this script:

    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null
    LogLevel ERROR
