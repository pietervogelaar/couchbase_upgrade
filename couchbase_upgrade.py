#!/usr/bin/env python

# couchbase_upgrade.py
# https://github.com/pietervogelaar/couchbase_upgrade
#
# Performs a rolling upgrade of a Couchbase cluster
#
# MIT License
#
# Copyright (c) 2017 Pieter Vogelaar
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import json
import re
import subprocess
import sys
import time
from distutils.version import StrictVersion


class CouchbaseUpgrader:
    """
    Performs a rolling upgrade of a Couchbase cluster
    """

    def __init__(self,
                 nodes,
                 username=None,
                 password=None,
                 port=8091,
                 cli='sudo /opt/couchbase/bin/couchbase-cli',
                 service_stop_command='sudo systemctl stop couchbase-server',
                 service_start_command='sudo systemctl start couchbase-server',
                 upgrade_command='sudo yum clean all && sudo yum install -y couchbase-server-community',
                 latest_version_command="sudo yum clean all >/dev/null 2>&1 && yum list all couchbase-server-community"
                                        " | grep couchbase-server-community | awk '{ print $2 }' | cut -d '-' -f1 |"
                                        " sort --version-sort -r | head -n 1",
                 version='latest',
                 upgrade_system_command='sudo yum clean all && sudo yum update -y',
                 upgrade_system=False,
                 reboot=False,
                 force_reboot=False,
                 verbose=False,
                 ):
        """
        Constructor
        :param nodes: list Host names or IP addresses of nodes
        :param username: string
        :param password: string
        :param port: int
        :param cli: string
        :param service_stop_command: string
        :param service_start_command: string
        :param upgrade_command: string
        :param latest_version_command: string
        :param version: string
        :param upgrade_system_command: string
        :param upgrade_system: string
        :param reboot: bool
        :param force_reboot: bool
        :param verbose: bool
        """

        self._nodes = nodes
        self._username = username
        self._password = password
        self._port = port
        self._cli = cli
        self._service_stop_command = service_stop_command
        self._service_start_command = service_start_command
        self._upgrade_command = upgrade_command
        self._latest_version_command = latest_version_command
        self._version = version
        self._upgrade_system_command = upgrade_system_command
        self._upgrade_system = upgrade_system
        self._reboot = reboot
        self._force_reboot = force_reboot
        self._verbose = verbose

        # Internal class attributes
        self._rebooting = False
        self._couchbase_upgrades_available = False
        self._os_upgrades_available = False

    def verbose_response(self, response):
        if self._verbose:
            print('Response status code: {}'.format(response.status_code))
            print('Response headers: {}'.format(response.headers))
            print('Response content: {}'.format(response.text))

    def current_version_lower(self, node):
        """
        Checks if the current version of Couchbase on the node
        is lower than the version to upgrade to
        :param node: string
        :return: bool
        """

        command = "{} server-info -c 127.0.0.1:{} -u {} -p '{}'".format(self._cli,
                                                                        self._port,
                                                                        self._username,
                                                                        self._password)

        result = self.ssh_command(node, command)
        if result['exit_code'] == 0:
            data = json.loads(result['stdout'])
            if 'version' in data:
                version_parts = data['version'].split('-')
                current_version = version_parts[0]

                if StrictVersion(current_version) == StrictVersion(self._version):
                    print('Skipping upgrade, the current version {} is the same as the version to upgrade to'
                          .format(current_version))
                    return False
                elif StrictVersion(current_version) > StrictVersion(self._version):
                    print('Skipping upgrade, the current version {} is higher than version {} to upgrade to'
                          .format(current_version, self._version))
                    return False
                else:
                    print('The current version {} is lower than version {} to upgrade to'
                          .format(current_version, self._version))
                    return True
            else:
                sys.stderr.write("Could not determine the current version\n")
        else:
            sys.stderr.write("Could not retrieve the current version\n")

        return False

    def stop_service(self, node):
        """
        Stops the Couchbase service on the node
        :param node: string
        :return: bool
        """

        result = self.ssh_command(node, self._service_stop_command)
        if result['exit_code'] != 0:
            return False

        return True

    def upgrade_couchbase(self, node):
        """
        Upgrades the Couchbase software on the node
        :param node: string
        :return: bool
        """

        result = self.ssh_command(node, self._upgrade_command)

        if self._verbose:
            print('stdout:')
            print(result['stdout'])
            print('stderr:')
            print(result['stderr'])

        if result['exit_code'] != 0:
            return False

        if 'Nothing to do' in result['stdout']:
            self._couchbase_upgrades_available = False
        else:
            self._couchbase_upgrades_available = True

        return True

    def upgrade_system(self, node):
        """
        Upgrades the operating system
        :param node: string
        :return: bool
        """
        result = self.ssh_command(node, self._upgrade_system_command)

        if self._verbose:
            print('stdout:')
            print(result['stdout'])
            print('stderr:')
            print(result['stderr'])

        if result['exit_code'] != 0:
            return False

        if 'No packages marked for update' in result['stdout']:
            self._os_upgrades_available = False
        else:
            self._os_upgrades_available = True

        return True

    def start_service(self, node):
        """
        Starts the Couchbase service on the node
        :param node: string
        :return: bool
        """

        result = self.ssh_command(node, self._service_start_command)
        if result['exit_code'] != 0:
            return False

        return True

    def wait_until_node_healthy(self, node):
        """
        Waits until the node is healthy
        :param node:
        :return: bool
        """

        print('- Waiting until node joins the cluster and is healthy')

        while True:
            time.sleep(5)

            if self.get_node_status(node) == 'healthy':
                if self._verbose:
                    print("Node joined the cluster and is healthy")
                else:
                    sys.stdout.write(".\n")
                    sys.stdout.flush()

                return True

            if self._verbose:
                print("Node hasn't joined the cluster or is not healthy yet")
            else:
                sys.stdout.write('.')
                sys.stdout.flush()

    def set_recovery_type(self, node, recovery_type):
        """
        Sets the recovery type for a node
        :param node: string
        :param recovery_type: string
        :return: bool
        """

        command = "{} recovery -c 127.0.0.1:{} -u {} -p '{}' --server-recovery {} --recovery-type {}"\
            .format(self._cli, self._port, self._username, self._password, node, recovery_type)

        result = self.ssh_command(node, command)
        if result['exit_code'] != 0:
            return False

        return True

    def rebalance(self, node):
        """
        Rebalances the cluster
        :param node: string
        :return:
        """
        command = "{} rebalance -c 127.0.0.1:{} -u {} -p '{}' --no-wait" \
            .format(self._cli, self._port, self._username, self._password)

        result = self.ssh_command(node, command)
        if result['exit_code'] != 0:
            return False

        return True

    def wait_until_rebalanced(self, node):
        """
        Waits until the cluster is rebalanced
        :param node:
        :return: bool
        """

        print('- Waiting until the cluster is rebalanced')

        while True:
            time.sleep(5)

            rebalance_status = self.get_rebalance_status(node)
            if rebalance_status == 'notRunning':
                if self._verbose:
                    print("Cluster is rebalanced")
                else:
                    sys.stdout.write(".\n")
                    sys.stdout.flush()

                return True

            if self._verbose:
                print("Cluster is not rebalanced yet")
            else:
                sys.stdout.write('.')
                sys.stdout.flush()

    def all_nodes_healthy(self, node):
        """
        Checks if all nodes in the cluster are healthy
        :param node: string
        :return: bool
        """

        all_nodes_healthy = True

        command = "{} server-list -c 127.0.0.1:{} -u {} -p '{}'".format(self._cli,
                                                                        self._port,
                                                                        self._username,
                                                                        self._password)

        result = self.ssh_command(node, command)
        if result['exit_code'] != 0:
            return False

        lines = result['stdout'].split("\n")
        for line in lines:
            if str(self._port) in line and 'healthy' not in line:
                all_nodes_healthy = False
                break

        return all_nodes_healthy

    def get_node_status(self, node):
        """
        Gets the node status
        :param node: string
        :return: string|bool
        """

        command = "{} server-info -c 127.0.0.1:{} -u {} -p '{}'".format(self._cli,
                                                                        self._port,
                                                                        self._username,
                                                                        self._password)

        regex = re.compile(r"Operation timed out", re.IGNORECASE)
        result = self.ssh_command(node, command, [regex])
        if result['exit_code'] != 0:
            return False

        data = json.loads(result['stdout'])

        if 'status' in data:
            return data['status']
        else:
            return False

    def get_rebalance_status(self, node):
        """
        Gets the rebalance status
        :param node: string
        :return: string|bool
        """

        command = "{} rebalance-status -c 127.0.0.1:{} -u {} -p '{}'" \
            .format(self._cli, self._port, self._username, self._password)

        result = self.ssh_command(node, command)
        if result['exit_code'] == 0:
            data = json.loads(result['stdout'])

            if 'status' in data:
                return data['status']

        return False

    def get_latest_version(self, node):
        """
        Gets the latest version available in the repository
        :param node: string
        :return: bool
        """

        result = self.ssh_command(node, self._latest_version_command)
        if result['exit_code'] != 0:
            return False

        latest_version = result['stdout'].strip()
        if StrictVersion(latest_version) > StrictVersion('0.0.0'):
            return latest_version

        return False

    def reboot(self, node):
        """
        Reboots the node
        :param node: string
        :return: None
        """

        print('- Rebooting')
        self._rebooting = True
        self.ssh_command(node, 'sudo /sbin/reboot')

    def ssh_command(self, host, command, hide_errors=[]):
        """
        Executes a SSH command
        :param host: string
        :param command: string
        :param hide_errors: list A list of compiled regular expressions to match errors that must be hidden
        :return: dict
        """
        p = subprocess.Popen(['ssh', '%s' % host, command],
                             shell=False,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)

        stdout = p.stdout.readlines()
        stderr = p.stderr.readlines()

        stdout_string = ''.join(stdout)
        stderr_string = ''.join(stderr)

        # Remove clutter
        regex = re.compile(r"Connection .+? closed by remote host\.\n?", re.IGNORECASE)
        stderr_string = regex.sub('', stderr_string).strip()

        for hide_error_regex in hide_errors:
            stderr_string = hide_error_regex.sub('', stderr_string).strip()

        if stderr_string:
            sys.stderr.write("SSH error from host {}: {}\n".format(host, stderr_string))

        # Make a return code available
        p.communicate()[0]

        result = {
            'stdout': stdout_string,
            'stderr': stderr_string,
            'exit_code': p.returncode,
        }

        return result

    def upgrade_node(self, node):
        """
        Upgrades the node
        :param node: string
        :return: bool
        """
        print('# Node {}'.format(node))

        self._rebooting = False

        if self._version:
            # Only upgrade node if the current version is lower than the version to upgrade to
            if not self.current_version_lower(node):
                # Couchbase already up to date

                if self._upgrade_system:
                    print('- Upgrading operating system')
                    if not self.upgrade_system(node):
                        sys.stderr.write("Failed to upgrade operating system\n")
                        return False
                    else:
                        if not self._os_upgrades_available:
                            print('No operating system upgrades available')

                if self._force_reboot or (self._reboot and self._os_upgrades_available):
                    self.reboot(node)
                else:
                    return True

        if not self._rebooting:
            # Stop Couchbase service
            print('- Stopping Couchbase service')
            if not self.stop_service(node):
                sys.stderr.write("Failed to stop Couchbase service\n")
                return False

            # Upgrade the Couchbase software
            print('- Upgrading Couchbase software')
            if not self.upgrade_couchbase(node):
                sys.stderr.write("Failed to upgrade Couchbase software\n")
                return False

            if self._upgrade_system:
                print('- Upgrading operating system')
                if not self.upgrade_system(node):
                    sys.stderr.write("Failed to upgrade operating system\n")
                    return False
                else:
                    if not self._os_upgrades_available:
                        print('No operating system upgrades available')

            if (self._force_reboot or
               (self._reboot and (self._couchbase_upgrades_available or self._os_upgrades_available))):
                self.reboot(node)

            if not self._rebooting:
                # Start Couchbase service
                print('- Starting Couchbase service')
                if not self.start_service(node):
                    sys.stderr.write("Failed to start Couchbase service\n")
                    return False

        self.wait_until_node_healthy(node)

        print('- Setting recovery type to delta')
        self.set_recovery_type(node, 'delta')

        print('- Rebalancing the cluster')
        if not self.rebalance(node):
            sys.stderr.write("Failed to rebalance the cluster\n")
            return False

        self.wait_until_rebalanced(node)

        print('- Checking if all nodes are healthy')
        if not self.all_nodes_healthy(node):
            sys.stderr.write("All nodes must be healthy after rebalancing finished, but are not\n")
            return False

        return True

    def upgrade(self):
        """
        Upgrades the cluster
        :return: bool
        """
        print('Performing a rolling upgrade of the Couchbase cluster')

        if self._verbose:
            print('Cluster nodes: {}'.format(json.dumps(self._nodes)))

        if self._version == 'latest':
            print('Determining the latest version')

            latest_version = self.get_latest_version(self._nodes[0])
            if latest_version:
                print('Using latest version {} as version to upgrade to'.format(latest_version))
                self._version = latest_version
            else:
                sys.stderr.write("Failed to determine the latest version\n")
                return False

        # Only start upgrading the cluster if all nodes are healthy
        print('Checking if all nodes are healthy')
        if not self.all_nodes_healthy(self._nodes[0]):
            sys.stderr.write("Did not start upgrading the cluster because not all nodes are healthy\n")
            return False

        # Only start upgrading the cluster if rebalance is not running
        print('Checking if rebalance is not running')
        if self.get_rebalance_status(self._nodes[0]) != 'notRunning':
            sys.stderr.write("Did not start upgrading the cluster because rebalance is running\n")
            return False

        for node in self._nodes:
            if not self.upgrade_node(node):
                sys.stderr.write("Failed to patch the Couchbase cluster\n")
                return False

        print ('Successfully upgraded all nodes of the Couchbase cluster')

        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Performs a rolling upgrade of a Couchbase cluster')
    parser.add_argument('-n', '--nodes', help='Comma separated list of host names or IP addresses of nodes',
                        required=True)
    parser.add_argument('-u', '--username', help="Username for authentication", required=True)
    parser.add_argument('-P', '--password', help="Password for authentication", required=True)
    parser.add_argument('-p', '--port', help='Couchbase HTTP port. Default 8091', type=int, default=8091)
    parser.add_argument('--cli',
                        help="Shell command to the Couchbase CLI. "
                             "Default 'sudo /opt/couchbase/bin/couchbase-cli'",
                        default='sudo /opt/couchbase/bin/couchbase-cli')
    parser.add_argument('--service-stop-command',
                        help="Shell command to stop the Couchbase service on a node. "
                             "Default 'sudo systemctl stop couchbase-server'",
                        default='sudo systemctl stop couchbase-server')
    parser.add_argument('--service-start-command',
                        help="Shell command to start the Couchbase service on a node. "
                             "Default 'sudo systemctl start couchbase-server'",
                        default='sudo systemctl start couchbase-server')
    parser.add_argument('--upgrade-command',
                        help="Command to upgrade Couchbase on a node. "
                             "Default 'sudo yum clean all && sudo yum install -y couchbase-server-community'",
                        default='sudo yum clean all && sudo yum install -y couchbase-server-community')
    parser.add_argument('--latest-version-command',
                        help="Command to get the latest version in the repository. "
                             "Default \"sudo yum clean all >/dev/null 2>&1 && sudo yum list all"
                             " couchbase-server-community | grep couchbase-server-community | awk '{ print $2 }' |"
                             " cut -d '-' -f1 | sort --version-sort -r | head -n 1\"",
                        default="sudo yum clean all >/dev/null 2>&1 && sudo yum list all couchbase-server-community |"
                                " grep couchbase-server-community | awk '{ print $2 }' | cut -d '-' -f1 |"
                                " sort --version-sort -r | head -n 1")
    parser.add_argument('--version',
                        help="A specific version to upgrade to or 'latest'. If 'latest', then the highest"
                             " available version in the repository will be determined. Nodes with a version"
                             " equal or higher will be skipped. Default 'latest'",
                        default='latest')
    parser.add_argument('--upgrade-system-command',
                        help="Command to upgrade operating system. Default 'sudo yum clean all && sudo yum update -y'",
                        default='sudo yum clean all && sudo yum update -y')
    parser.add_argument('--upgrade-system', help='Upgrades the operating system also after upgrading Couchbase',
                        action='store_true')
    parser.add_argument('--reboot', help='Reboots the server if an actual upgrade took place', action='store_true')
    parser.add_argument('--force-reboot', help='Always reboots the server, even though no upgrade occurred because'
                                               ' the version was already the latest', action='store_true')
    parser.add_argument('-v', '--verbose', help='Display of more information', action='store_true')
    args = parser.parse_args()

    # Create nodes list from comma separated string
    nodes = args.nodes.replace(' ', '').split(',')

    couchbase_upgrader = CouchbaseUpgrader(nodes,
                                       args.username,
                                       args.password,
                                       args.port,
                                       args.cli,
                                       args.service_stop_command,
                                       args.service_start_command,
                                       args.upgrade_command,
                                       args.latest_version_command,
                                       args.version,
                                       args.upgrade_system_command,
                                       args.upgrade_system,
                                       args.reboot,
                                       args.force_reboot,
                                       args.verbose)

    if not couchbase_upgrader.upgrade():
        exit(1)
