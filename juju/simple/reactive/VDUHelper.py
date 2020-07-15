#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =====================================================================
#     #######  #####          #     #   ###   #     # #     #   ###
#     #       #     #         #     #    #    ##    # ##    #    #
#     #       #               #     #    #    # #   # # #   #    #
#      #####  #  ####  #####  #     #    #    #  #  # #  #  #    #
#           # #     #          #   #     #    #   # # #   # #    #
#     #     # #     #           # #      #    #    ## #    ##    #
#      #####   #####             #      ###   #     # #     #   ###
# =====================================================================
#
# SimulaMet OpenAirInterface Evolved Packet Core NS
# Copyright (C) 2019 by Thomas Dreibholz
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Contact: dreibh@simula.no

import ipaddress
import logging
import logging.config
import os
import subprocess
import sys
import traceback

from charmhelpers.core.hookenv import (
    action_get,
    action_fail,
    action_set,
    status_set
)
from charms.reactive import (
    clear_flag,
    set_flag,
    when,
    when_not
)
import charms.sshproxy



# ###########################################################################
# #### Helper functions                                                  ####
# ###########################################################################

# ###### Execute command ####################################################
def execute(commands):
   return charms.sshproxy._run(commands)



# ###########################################################################
# #### VDUHelper class                                                   ####
# ###########################################################################

class VDUHelper:
   # ###### Constructor #####################################################
   def __init__(self, logFileName):
      # ====== Initialise object ============================================
      self.blockStack = []

      # ====== Initialise logger ============================================
      loggingConfiguration = {
         'version': 1,
         'handlers': {
            'default': {
               'level':     'DEBUG',
               'class':     'logging.handlers.TimedRotatingFileHandler',
               'formatter': 'standard',
               'filename':  logFileName,
               'when':      'D'
            },
         },
         'formatters': {
            'standard': {
               'format': '%(asctime)s %(levelname)s [PID=%(process)d] %(message)s'
            },
         },
         'root': {
            'level': 'DEBUG',
            'handlers': ['default'],
         }
      }
      logging.config.dictConfig(loggingConfiguration)
      logging.debug('Starting')


   # ###### Begin block #####################################################
   def beginBlock(self, label):
      self.blockStack.append(label)
      logging.debug(label + ' ...')


   # ###### End block #######################################################
   def endBlock(self, success = True):
      assert len(self.blockStack) > 0
      label = self.blockStack.pop()
      if success == True:
         logging.debug(label + ' completed!')
      else:
         logging.debug(label + ' FAILED!')
         print(label + ' FAILED!')


   # ###### Run shell commands and handle exceptions ########################
   def runInShell(self, commands, raiseExceptionOnError = True):
      try:
         execute(commands)
      except:
         message = 'Command execution failed: ' + commands
         logging.error(message)
         if raiseExceptionOnError:
            raise
         return False
      else:
         return True


   # ######  Get /etc/network/interfaces setup for interface ###################
   def makeInterfaceConfiguration(self,
                                  interfaceName,
                                  ipv4Interface = ipaddress.IPv4Interface('0.0.0.0/0'),
                                  ipv4Gateway   = None,
                                  ipv6Interface = None,
                                  ipv6Gateway   = None,
                                  metric        = 1,
                                  pdnInterface  = None):

      # NOTE:
      # Double escaping is required for \ and " in "interfaceConfiguration" string!
      # 1. Python
      # 2. bash -c "<command>"
      # That is: $ => \$ ; \ => \\ ; " => \\\"

      interfaceConfiguration = 'auto ' + interfaceName + '\\\\n'

      # ====== Helper function =================================================
      def makePDNRules(pdnInterface, interface, gateway):
         rules = \
            '\\\\tpost-up /bin/ip rule add from ' + str(interface.network) + ' lookup 1000 pref 100\\\\n' + \
            '\\\\tpost-up /bin/ip rule add iif pdn lookup 1000 pref 100\\\\n' + \
            '\\\\tpost-up /bin/ip route add ' + str(interface.network) + ' scope link dev ' + interfaceName + ' table 1000\\\\n' + \
            '\\\\tpost-up /bin/ip route add default via ' + str(gateway) + ' dev ' + interfaceName + ' table 1000\\\\n' + \
            '\\\\tpre-down /bin/ip route del default via ' + str(gateway) + ' dev ' + interfaceName + ' table 1000 || true\\\\n' + \
            '\\\\tpre-down /bin/ip route del ' + str(interface.network) + ' scope link dev ' + interfaceName + ' table 1000 || true\\\\n' + \
            '\\\\tpre-down /bin/ip rule del iif pdn lookup 1000 pref 100 || true\\\\n' + \
            '\\\\tpre-down /bin/ip rule del from ' + str(interface.network) + ' lookup 1000 pref 100 || true\\\\n'
         return rules

      # ====== IPv4 ============================================================
      if ipv4Interface == ipaddress.IPv4Interface('0.0.0.0/0'):
         interfaceConfiguration = interfaceConfiguration + 'iface ' + interfaceName + ' inet dhcp'
      else:
         interfaceConfiguration = interfaceConfiguration + \
            'iface ' + interfaceName + ' inet static\\\\n' + \
            '\\\\taddress ' + str(ipv4Interface.ip)      + '\\\\n' + \
            '\\\\tnetmask ' + str(ipv4Interface.netmask) + '\\\\n'
         if ((ipv4Gateway != None) and (ipv4Gateway != IPv4Address('0.0.0.0'))):
            interfaceConfiguration = interfaceConfiguration + \
               '\\\\tgateway ' + str(ipv4Gateway) + '\\\\n' + \
               '\\\\tmetric '  + str(metric)      + '\\\\n'
         if pdnInterface != None:
            interfaceConfiguration = interfaceConfiguration + makePDNRules(pdnInterface, ipv4Interface, ipv4Gateway)
         interfaceConfiguration = interfaceConfiguration + '\\\\n'

      # ====== IPv6 ============================================================
      if ipv6Interface == None:
         interfaceConfiguration = interfaceConfiguration + \
            '\\\\niface ' + interfaceName + ' inet6 manual\\\\n' + \
            '\\\\tautoconf 0\\\\n'
      elif ipv6Interface == IPv6Interface('::/0'):
         interfaceConfiguration = interfaceConfiguration + \
            '\\\\niface ' + interfaceName + ' inet6 dhcp\\\\n' + \
            '\\\\tautoconf 0\\\\n'
      else:
         interfaceConfiguration = interfaceConfiguration + \
            '\\\\niface ' + interfaceName + ' inet6 static\\\\n' + \
            '\\\\tautoconf 0\\\\n' + \
            '\\\\taddress ' + str(ipv6Interface.ip)                + '\\\\n' + \
            '\\\\tnetmask ' + str(ipv6Interface.network.prefixlen) + '\\\\n'
         if ((ipv6Gateway != None) and (ipv6Gateway != IPv6Address('::'))):
            interfaceConfiguration = interfaceConfiguration + \
               '\\\\tgateway ' + str(ipv6Gateway) + '\\\\n' + \
               '\\\\tmetric '  + str(metric)      + '\\\\n'
         if pdnInterface != None:
            interfaceConfiguration = interfaceConfiguration + makePDNRules(pdnInterface, ipv6Interface, ipv6Gateway)

      return interfaceConfiguration


   # ###### Configuration and activate network interface ####################
   def configureInterface(self, interfaceName, interfaceConfiguration):
      self.beginBlock('Configuring and activating ' + interfaceName)
      commands = """\
echo -e \\\"{interfaceConfiguration}\\\" | sudo tee /etc/network/interfaces.d/61-{interfaceName} && sudo ifup {interfaceName} || true""".format(
         interfaceName          = interfaceName,
         interfaceConfiguration = interfaceConfiguration
      )
      self.runInShell(commands)
      self.endBlock()


   # ###### Test networking #################################################
   def testNetworking(self, destination = ipaddress.IPv4Address('8.8.8.8'), timeout = 60):
      self.beginBlock('Testing networking')

      try:
         commands = """ping -W{timeout} -c3 {destination}""".format(
            destination = str(destination),
            timeout     = timeout
         )
         self.runInShell(commands)
      except:
         self.endBlock(False)
         raise

      self.endBlock()
