# See README.md for information and usage.
#
# Copyright 2016 Christopher Allen Ogden
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import mailbox
import re
import sys

# Patterns of text to delete from messages.
DELETION_PATTERS = [
    # Reply text:
    r"(\n|^)On.*\n?.*wrote:\n+(.|\n)*$",
    r"(\n|^)From:(.|\n)*$",
    # Forwarded messages:
    r"(\n|^)---------- Forwarded message ----------(.|\n)*$",
    # PGP:
    r"(\n|^)-----BEGIN PGP MESSAGE-----\n(.|\n)*-----END PGP MESSAGE-----\n",
    # Embedded links:
    r"<[^ ]+>",
]


def munge_message(text):
    """
    Munges an e-mail message (in text form).

    :param text: The e-mail message.
    :return: The munged e-mail message.
    """
    for pattern in DELETION_PATTERS:
        text = re.sub(pattern, "", text)
    return text


def unquoted_line(line):
    """
    Unquotes an e-mail message line according to RFC 3676.

    :param line: The (possibly quoted) message line.
    :return: (unquoted line, quote depth).
    """
    quote_depth = 0
    while line.startswith(">"):
        line = line[1:]
        quote_depth += 1
    return line, quote_depth


def unstuff_line(line):
    """
    Unstuffs an e-mail message line according to RFC 3637.

    :param line: The (possibly stuffed) message line.
    :return: The unstuffed message line.
    """
    if line.startswith(" "):
        return line[1:]
    return line


def unflow_line(line, delsp):
    """
    Unflows an e-mail message line according to RFC 3637.

    :param line: The (possibly soft-broken) message line.
    :param delsp: Whether or not soft-break spaces should be deleted.
    :return: (processed line, soft-broken)
    """
    if len(line) < 1:
        return line, False
    if line.endswith(" "):
        if delsp:
            line = line[:-1]
        return line, True
    return line, False


def unflow_text(text, delsp):
    """
    Unflows an e-mail message according to RFC 3637.

    :param text: The flowed message.
    :param delsp: Whether or not soft-break spaces should be deleted.
    :return: The processed message.
    """
    full_line = ""
    full_text = ""
    lines = text.splitlines()
    for line in lines:
        (line, quote_depth) = unquoted_line(line)
        line = unstuff_line(line)
        (line, soft_break) = unflow_line(line, delsp)
        full_line += line
        if not soft_break:
            full_text += ">" * quote_depth + full_line + "\n"
            full_line = ""
    return full_text


def part_to_text(part):
    """
    Converts an e-mail message part into text.

    Returns None if the message could not be decoded as ASCII.

    :param part: E-mail message part.
    :return: Message text.
    """
    if part.get_content_type() != "text/plain":
        return None
    charset = part.get_content_charset()
    if not charset:
        return None

    text = part.get_payload(decode=True).decode(encoding=charset, errors="ignore")

    # this leaves ascii-only emails, which we don't want
    """
    try:
        # text = text.encode("ascii").decode("ascii")
        text = text.encode("utf-8").decode("utf-8")
    except UnicodeEncodeError:
        return None
    except UnicodeDecodeError:
        return None
    """

    if part.get_param("format") == "flowed":
        text = unflow_text(text, part.get_param("delsp", False))
    return text


def message_to_text(message):
    """
    Converts an e-mail message into text.

    Returns an empty string if the e-mail message could not be decoded as ASCII.

    :param message: E-mail message.
    :return: Message text.
    """
    text = ""
    for part in message.walk():
        part = part_to_text(part)
        if part:
            text += part
    return text


def clean_subject(subject):
    """
    Clean the subject line by removing common thread prefixes like "Re:" and "Fwd:".

    :param subject: The subject line of an email message.
    :return: The cleaned subject line.
    """
    return re.sub(r"^(Re:|Fwd:)\s*", "", subject, flags=re.IGNORECASE).strip()


def get_thread_identifier(message):
    """
    Obtain a thread identifier from an email message.

    :param message: The email message object.
    :return: A string that uniquely identifies the thread this message belongs to.
    """

    # items = message.items()

    # Attempt to use the 'In-Reply-To' header first
    in_reply_to = message.get("In-Reply-To")
    if in_reply_to:
        return in_reply_to.strip()

    # Fall back to using a cleaned 'Subject' line if 'In-Reply-To' is not available
    subject = message.get("Subject", "")
    return clean_subject(subject)


def mailbox_text(mb, author):
    """
    Returns the contents of a mailbox as text.

    Excludes messages to 'author' and not from 'author'.

    :param mb: Mailbox over which to iterate.
    :param author: Excludes messages to and not from this author.
    :return: Nothing.
    """
    for message in mb:
        if not message["From"]:
            continue
        if author not in message["From"]:
            continue
        if not message["To"]:
            continue
        if author in message["To"]:
            continue
        text = message_to_text(message)
        text = munge_message(text)
        if text and len(text) > 0:
            yield text


def mailbox_text_thread(mb, author):
    """
    Returns the contents of a mailbox as text, grouped by threads.

    Includes entire conversation threads that involve 'author'.

    :param mb: Mailbox over which to iterate.
    :param author: Include threads involving this author.
    :return: Threads of messages.
    """
    threads = {}  # Dictionary to hold threads, keyed by a common thread identifier

    # Process each message in the mailbox
    for message in mb:
        # Determine the thread identifier (this could be a combination of subject and header IDs)
        thread_id = get_thread_identifier(message)

        # If a thread with this identifier does not exist, create it
        if thread_id not in threads:
            threads[thread_id] = []

        # Add the message to the thread
        threads[thread_id].append(message)

    # Sort messages within each thread by date
    for thread in threads.values():
        thread.sort(key=lambda msg: msg.get("Date", ""))

    # Yield the threads
    for thread_id, messages in threads.items():
        # print("Debug: yield thread: {}\n".format(thread_id))
        yield thread_id, messages


def main():
    parser = argparse.ArgumentParser(description="Convert mbox to text file.")
    parser.add_argument("mbox_file", help=".mbox file to parse")
    parser.add_argument("author", help="author to exclude")
    args = parser.parse_args()

    # threads
    mb = mailbox.mbox(args.mbox_file, create=False)
    for thread_id, messages in mailbox_text_thread(mb, args.author):
        # print("Thread: {}\n".format(thread_id))
        print("Email thread {}:\n".format(thread_id))
        for message in messages:
            subject = clean_subject(message.get("Subject", ""))
            text = message_to_text(message)
            text = munge_message(text)
            if text and len(text) > 0:
                subject_utf = subject.encode("utf-8")
                text_utf = text.encode("utf-8")

                print("Subject: {}".format(subject_utf))
                print("")
                print(text_utf)
                print("\n----\n")
            sys.stderr.write(text_utf[:20] + "\n")

    # single messages
    # mb = mailbox.mbox(args.mbox_file, create=False)
    # for text in mailbox_text(mb, args.author):
    #     print(text)
    #     print("\n----\n")
    #     sys.stderr.write(text[:20] + "\n")


if __name__ == "__main__":
    main()
