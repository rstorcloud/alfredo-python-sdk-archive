#!/usr/bin/env python

"""Alfredo Command Line Interface

Usage:
    alfredo login [-i <input>]
    alfredo logout
    alfredo ruote [-C|-R|-U|-D|-X] [-i <input>] [-o <output>] <path>...

Options:

    Operations:

        -C  --create    Create.
        -R  --retrieve  Retrieve (default operation).
        -X  --replace   Replace.
        -U  --update    Update.
        -D  --delete    Delete.

    Input:

        -i <input> --input <input>
                        <input> is a valid JSON or YAML string with the object to be sent to the operation.
                        If not given, and input required, it is fetched from <stdin>.

    Output:

        -o <output> --output <output>
                        <output> is a dot-separated list of attributes to navigate from a list or object.
                        You can use numbers to select items of an array. Negative numbers allowed.
                        You can use commas to get several attributes
                        Examples:
                            alfredo ruote apps -o name
                            alfredo ruote jobs -o id,name,queue
                            alfredo ruote apps -o 0
                            alfredo ruote jobs id:723 -o output_files

    Others:

        -h --help       Show this screen.
        -V --version    Show version.

    Examples:

        Register a new user

            alfredo ruote users -C -i "{password: '****', email: alice@example.com}"

        Get a token

            alfredo ruote sso token_by_email -C -i "{password: '****', email: alice@example.com}"

        Login (and store the token for future usage)

            alfredo login -i "{password: '****', email: alice@example.com}"

        Get the current user info

            alfredo ruote users me

        Change the first name of the current user

            alfredo ruote users me -U -i "first_name: Bob"

        Get the details of a user by id

            alfredo ruote users id:343

        Get the list of clusters

            alfredo ruote clusters

        Create a cluster given a name

            alfredo ruote clusters -C -i "name: example cluster"

        Get the list of queues

            alfredo ruote queues

        Create a queue

            alfredo ruote queues -C -i "{cluster: 383, name: q}"

        List the user files

            alfredo ruote files

        Upload a file from a local path

            alfredo ruote files -C -i "file: /home/alice/test.txt"

        Delete a file by id

            alfredo ruote files id:51 -D

        Create an app

            alfredo ruote apps -C -i "{container_checksum: 00000000000, name: app, container_url: http://app.example.com/}"

        Create a job

             alfredo ruote jobs -C -i '{name: job, queue: 12, app: 243}'

"""

import os.path
import re
import sys

import ruamel.yaml as yaml
from docopt import docopt

import alfredo


def represent_unicode(self, data):
    return self.represent_str(data.encode('utf-8'))


if sys.version_info < (3,):
    yaml.representer.Representer.add_representer(unicode, represent_unicode)

__version__ = '0.0.1'


class Command(object):
    def __init__(self, arguments):
        self._arguments = arguments

    @property
    def token_file(self):
        return '.token'

    def is_logged_in(self):
        return os.path.isfile(self.token_file)

    @property
    def token(self):
        if self.is_logged_in():
            return open(self.token_file, 'r').read()
        return None

    @property
    def input(self):
        if self._arguments['--input']:
            return self.input_from_argv()
        else:
            return self.input_from_stdin()

    def input_from_argv(self):
        return yaml.safe_load(self._arguments['--input'])

    def input_from_stdin(self):
        if sys.stdin.isatty():
            sys.stdout.write("Enter input:\n")

        return yaml.safe_load(sys.stdin.read()) or {}

    def run(self):
        raise NotImplementedError()


class LoginCommand(Command):
    def run(self):
        response = alfredo.ruote().sso.token_by_email.create(**self.input)
        if response.ok:
            with open(self.token_file, 'w') as f:
                f.write(response.token)
        else:
            print(response)
        return response.exit_code


class LogoutCommand(Command):
    def run(self):
        if self.is_logged_in():
            os.remove(self.token_file)
            return 0
        return 1


class RuoteCommand(Command):
    def run(self):
        response = self.get_response()
        self.print_response(response)
        return response.exit_code

    def get_response(self):
        target = self.get_target()

        if self._arguments['-C']:
            response = target.create(**self.input)
        elif self._arguments['-U']:
            response = target.update(**self.input)
        elif self._arguments['-X']:
            response = target.replace(**self.input)
        elif self._arguments['-D']:
            response = target.delete()
        else:
            response = target.retrieve()

        return response

    def get_target(self):
        ruote = alfredo.ruote(token=self.token)
        target = ruote
        for p in self._arguments['<path>']:
            try:
                call = re.search('([^:]+):(.+)', p)
                if call:
                    try:
                        target = getattr(target, call.group(1))(call.group(2))
                    except AttributeError:
                        target = getattr(target, p)
                else:
                    target = getattr(target, p)
            except AttributeError:
                sys.stderr.write("Unknown path\n")
                exit(1)
        return target

    def print_response(self, response):
        if self._arguments['--output']:
            self.print_output_attrs(response)
        else:
            print(response)

    def print_output_attrs(self, response):
        result = response.native()
        attr_list = self._arguments['--output'].split(',')
        result = self.pluck(result, attr_list=attr_list)
        print(yaml.dump(result, default_flow_style=False).rstrip('\n'))

    def pluck(self, dict_or_list, attr_list):
        if not attr_list:
            return dict_or_list

        if isinstance(dict_or_list, list):
            return self.pluck_list(dict_or_list, attr_list)
        else:
            return self.pluck_dict(dict_or_list, attr_list)

    def pluck_list(self, target_list, attr_list):
        if len(attr_list) == 1 and re.search('^[0-9]+$', attr_list[0]):
            return target_list[int(attr_list[0])]
        else:
            return [self.pluck(item, attr_list) for item in target_list]

    def pluck_dict(self, target_dict, attr_list):
        if len(attr_list) == 1:
            return self.pluck_dict_dot(target_dict, attr_list[0].split('.'))
        elif len(attr_list) > 1:
            return {key.strip(): self.pluck(target_dict, [key]) for key in attr_list if key != ''}

    def pluck_dict_dot(self, target_dict, attr_dot_list):
        if len(attr_dot_list) > 1:
            return self.pluck_dict_dot(target_dict[attr_dot_list[0].strip()], attr_dot_list[1:])
        elif len(attr_dot_list) == 1:
            return target_dict[attr_dot_list[0].strip()]
        else:
            return target_dict


class CLI(object):
    commands = {
        'login': LoginCommand,
        'logout': LogoutCommand,
        'ruote': RuoteCommand,
    }

    @staticmethod
    def run(doc, version):
        arguments = docopt(doc=doc, version=version)

        for command_name in CLI.commands.keys():
            if arguments[command_name]:
                exit_code = CLI.commands[command_name](arguments).run()
                if sys.argv[0] == 'alfredo':
                    CLI.cleanup()
                exit(exit_code)

    @staticmethod
    def cleanup(*args):
        CLI.safe_call(sys.stderr.flush)
        CLI.safe_call(sys.stderr.close)

        CLI.safe_call(sys.stdout.flush)
        CLI.safe_call(sys.stdout.close)

    @staticmethod
    def safe_call(callable):
        try:
            callable()
        except:
            pass


def main():
    sys.excepthook = CLI.cleanup
    CLI.run(__doc__, __version__)

if __name__ == '__main__':
    main()
