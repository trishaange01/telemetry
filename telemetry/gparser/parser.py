from urllib.parse import urlparse
import json
import os
import re
import traceback
import junitparser
import telemetry
from junitparser import JUnitXml, Skipped, Error, Failure
import xml.etree.ElementTree as ET
import ast
from bs4 import BeautifulSoup
import asyncio
import aiohttp

def get_parser(url,grabber=None):
    '''Factory method that provides appropriate parser object base on given url'''
    parsers = {
        '^.*dmesg_[a-zA-Z0-9-]+\.log': Dmesg,
        '^.*dmesg_.+err\.log': DmesgError,
        '^.*dmesg_.+warn\.log': DmesgWarning,
        '^.*enumerated_devs\.log': EnumeratedDevs,
        '^.*missing_devs\.log': MissingDevs,
        '^.*pyadi-iio.*\.xml': [PytestFailure, PytestSkipped, PytestError],
        '^.*HWTestResults\.xml': [MatlabFailure, MatlabSkipped, MatlabError],
        '^.*info\.txt': InfoTxt,
    }

    # find parser
    for sk, parser in parsers.items():
        if re.match(sk, url):
            if isinstance(parser, list):
                return [p(url, grabber) for p in parser]
            return parser(url, grabber)

    raise Exception("Cannot find Parser for {}".format(url))

def remove_suffix(input_string, suffix):
    if suffix and input_string.endswith(suffix):
        return input_string[:-len(suffix)]
    return input_string

class Parser():
    '''Base class for a parser object'''
    def __init__(self, url, grabber=None):
        
        self.url = url
        self.server = None
        self.job = None
        self.job_no = None
        self.job_date = None
        self.file_name = None
        self.file_info = None
        self.target_board = None
        self.artifact_info_type = None
        self.payload_raw = []
        self.payload = []
        self.payload_param = []
        if not grabber:
            self.grabber = telemetry.grabber.Grabber()
        else:
            self.grabber = grabber
        self.initialize()

    def initialize(self):
        url_ = urlparse(self.url)
        self.multilevel = False
        if len(url_.path.split('/job/')) > 2:
            self.multilevel = True

        # initialize attributes
        self.server = url_.scheme + '://' + url_.netloc + '/' + url_.path.split('/')[1]
        self.job, self.job_no, self.job_date  = self.get_job_info()
        file_info = self.get_file_info()
        self.file_name = file_info[0]
        self.file_info = file_info[1]
        self.target_board = file_info[2]
        self.artifact_info_type=file_info[3]
        self.payload_raw=self.get_payload_raw()
        payload_parsed=self.get_payload_parsed()
        if isinstance(payload_parsed, tuple):
            self.payload=payload_parsed[0]
            self.payload_param=payload_parsed[1]
        else:
            self.payload=payload_parsed
            self.payload_param=self.get_payload_param() 

    def show_info(self):
        return self.__dict__

    def get_job_info(self):
        '''returns jenkins project name, job no and job date'''
        if self.multilevel:
            url = urlparse(self.url)
            job=url.path.split('/')[3] + '/' + url.path.split('/')[5]
            job_no=url.path.split('/')[6]
            # TODO: get job date using jenkins api
            job_date=None
            return (job,job_no,job_date)

        raise Exception("Does not support non multilevel yet!")

    def get_file_info(self):
        '''returns file name, file info, target_board, artifact_info_type'''
        if self.multilevel:
            url = urlparse(self.url)
            file_name = url.path.split('/')[-1]
            file_info = file_name.split('_')
            target_board=file_info[0]
            artifact_info_type=file_info[1] + '_' + file_info[2]
            artifact_info_type = remove_suffix(artifact_info_type,".log")
            return (file_name, file_info, target_board, artifact_info_type)

        raise Exception("Does not support non multilevel yet!")


    def get_payload_raw(self):
        payload = []
        try:
            file_path = self.grabber.download_file(self.url, self.file_name)
            with open(file_path, "r") as f:
                payload = [l.strip() for l in f.readlines()]
        except Exception as ex:
            traceback.print_exc()
            print("Error Parsing File!")
        finally:
            os.remove(file_path)
        return payload

    def get_payload_parsed(self):
        payload = []
        for p in self.payload_raw:
            # try to extract timestamp from data
            x = re.search("\[.*(\d+\.\d*)\]\s(.*)", p)
            if x:
                payload.append((x.group(1),x.group(2)))
            else:
                x = re.search("(.*)", p)
                payload.append(x.group(1))
        return payload
    
    def get_payload_param(self):
        payload_param = list()
        for k in self.payload:
            payload_param.append("NA")
        return payload_param

class Dmesg(Parser):

    def __init__(self, url, grabber):
        super(Dmesg, self).__init__(url, grabber)

    def get_file_info(self):
        '''returns file name, file info, target_board, artifact_info_type'''
        if self.multilevel:
            url = urlparse(self.url)
            file_name = url.path.split('/')[-1]
            file_info = file_name.split('_')
            target_board=file_info[1]
            artifact_info_type=file_info[0]
            if len(file_info) == 3:
                artifact_info_type += '_' + file_info[2]
            artifact_info_type = remove_suffix(artifact_info_type,".log")
            return (file_name, file_info, target_board, artifact_info_type)

        raise Exception("Does not support non multilevel yet!")

class DmesgError(Dmesg):
    
    def __init__(self, url, grabber):
        super(DmesgError, self).__init__(url, grabber)

class DmesgWarning(Dmesg):
    
    def __init__(self, url, grabber):
        super(DmesgWarning, self).__init__(url, grabber)

class EnumeratedDevs(Parser):
    
    def __init__(self, url, grabber):
        super(EnumeratedDevs, self).__init__(url, grabber)

class MissingDevs(Parser):
    
    def __init__(self, url, grabber):
        super(MissingDevs, self).__init__(url, grabber)

class xmlParser(Parser):
    def __init__(self, url, grabber):
        super(xmlParser, self).__init__(url, grabber)
        
    def get_file_info(self):
        '''returns file name, file info, target_board, artifact_info_type'''
        if self.multilevel:
            url = urlparse(self.url)
            url_path = url.path.split('/')
            file_name = url_path[-1]
            parser_type = type(self).__name__
            x = [i for i, c in enumerate(parser_type) if c.isupper()]
            file_info = (parser_type[:x[1]]+'_'+parser_type[x[1]:]).lower()
            target_board = file_name.replace('_','-')
            target_board = remove_suffix(target_board,"-reports.xml")
            target_board = remove_suffix(target_board,"-HWTestResults.xml")
            artifact_info_type=file_info
            return (file_name, file_info, target_board, artifact_info_type)

        raise Exception("Does not support non multilevel yet!")
        
    def get_payload_raw(self):
        payload = []
        try:
            file_path = self.grabber.download_file(self.url, self.file_name)
            # Parser
            xml = JUnitXml.fromfile(file_path)
            resultType = getattr(junitparser, self.file_info.split("_")[1].capitalize())
            for suite in xml:
                for case in suite:
                    if case.result and type(case.result[0]) is resultType:
                        payload.append(case.name)
        except Exception as ex:
            traceback.print_exc()
            print("Error Parsing File!")
        finally:
            os.remove(file_path)
        return payload
    
    def get_payload_parsed(self):
        num_payload = len(self.payload_raw)
        procedure = list(range(num_payload))
        param = list(range(num_payload))
        for k, payload_str in enumerate(self.payload_raw):
            # remove trailing adi.xxxx device name
            payload_str = re.sub("-adi\.\w*", "", payload_str)
            # remove multiple dashes
            payload_str = re.sub("-+", "-", payload_str)
            # replace () from MATLAB xml with []
            payload_str = payload_str.replace("(","[").replace(")","]")
            procedure_param = payload_str.split("[")
            procedure[k] = procedure_param[0]
            if len(procedure_param) == 2:
                # remove path from profile filename
                if any(x in procedure[k] for x in ["profile_write", "write_profile"]):
                    param[k] = re.findall("(\w*\..*)]",procedure_param[1])[0]
                else:
                    param[k] = procedure_param[1][:-1]
            else:
                param[k] = "NA"
        payload = procedure
        payload_param = param
        return (payload, payload_param)

class pytestxml_parser(xmlParser):
    def __init__(self, url, grabber):
        super(pytestxml_parser, self).__init__(url, grabber)
    
    def get_payload_raw(self):
        payload = []
        try:
            file_path = self.grabber.download_file(self.url, self.file_name)
            # Load and parse the XML using element tree 
            tree = ET.parse(file_path)
            root = tree.getroot()              

            # Iterate over all test cases
            for testcase in root.findall(".//testcase"):
                # Get the name of the test case
                test_name = testcase.get("name")
                # Find the properties tag
                properties = testcase.find("properties")
                # Find the failure tag
                failure = testcase.find("failure")    

                # Test description links from pyadi-iio
                attr_link = "https://analogdevicesinc.github.io/pyadi-iio/dev/test_attr.html"
                dma_link = "https://analogdevicesinc.github.io/pyadi-iio/dev/test_dma.html"
                generic_link = "https://analogdevicesinc.github.io/pyadi-iio/dev/test_generics.html"
                # Set default description link for all tests
                test_name_link = f"[{test_name}]({attr_link})"    

                url_links = [attr_link, dma_link, generic_link]

                # Get parameters from test case name
                param_parsed = test_name.split("[", 1)
                test_name = param_parsed[0]
                param_parsed_last = (param_parsed[-1])[:-1].strip()
                # Separate the parameters
                param_separate = re.split(r'-(?!\d)', param_parsed_last)
                # Check parameters list for a dictionary named "param_set"
                for index, param in enumerate(param_separate):
                    # Check if param_set parameter name exists
                    if "param_set" in param:
                        param_list = []
                        # Remove param_set= in string
                        new_param = param[len("param_set="):].strip()
                        # Check if param is a dictionary and not empty
                        if new_param[0] == "{" and new_param != "\{\}":
                            # Convert remaining string to a dictionary
                            param_dict = ast.literal_eval(new_param)
                            if param_dict:
                                for key, value in param_dict.items():
                                    # Convert parameters of param_set back to string
                                    new_updated = "'" + key + "'" + ": " + str(value)
                                    param_list.append(new_updated)
                                param_list.insert(0, "param_set=")
                                param_list_string = "   \n".join(param_list)
                                # Update param in param_separate list
                                param_separate[index] = param_list_string 
                # Compile final parameter details
                param_separate.insert(0,"**Parameters:**")
                param_display = "\n  - ".join(param_separate) 

                if properties is not None:
                    if  failure is not None:
                        # Get failure tag content
                        failure_text = failure.text
                        fail_content_lines = failure_text.splitlines()
                        exc_param_value = ""
                        # Get exception statement with parameter names
                        for item in fail_content_lines[::-1]:
                            if len(item) > 0:
                                if item[0] == ">":
                                    exc_param_value = item[1:].lstrip()
                                    break                        
                                                                     
                        test_desc = ""
                        exctype_message = ""
                        # Iterate through each property in the properties tag
                        for prop in properties.findall("property"):
                            # Get the property name and value
                            prop_name = prop.get("name")
                            prop_value = prop.get("value")
                            if prop_name == "exception_type_and_message":                                                             
                                prop_list = prop_value.splitlines() 
                                new_props = prop_value
                                prop_list_updated = []
                                # Check if exception and message has mutiple lines  
                                if len(prop_list) > 1:
                                    for props in prop_list:
                                        if len(props) > 0:
                                            # Remove leading spaces
                                            prop_strip = props.lstrip()
                                            prop_list_updated.append(prop_strip)                                        
                                if len(prop_list_updated) > 0:
                                    new_props = " ".join(prop_list_updated)                                            
                                # Combine exception type, message, and parameters        
                                exctype_message =  "\n" + "  " + new_props + " ( " + exc_param_value + " )"
                            if prop_name == "test_description":
                                # Get test description
                                test_desc = prop_value

                            # Get test name from test description
                            if test_desc != "":
                                test_desc_split = test_desc.split(":")
                                if len(test_desc_split) > 0:
                                    test_desc_name = test_desc_split[0].strip()   

                                    # Search test name from description on pyad-iio test description links
                                    timeout_value = 5  # Timeout after 5 seconds for fetching URL
                                    
                                    # Asynchronous function to fetch and process the URL
                                    async def fetch_and_process(url, session):                                        
                                        try:
                                            async with session.get(url, timeout=timeout_value) as response:
                                                if response.status == 200:
                                                    page_content = await response.text()

                                                    # Parse the page content with BeautifulSoup
                                                    soup = BeautifulSoup(page_content, 'html.parser')

                                                    # Find all <dt> tags with the specific target class
                                                    dt_tags = soup.find_all('dt', class_='sig sig-object py')

                                                    for dt in dt_tags:
                                                        # Find all links in dt tags
                                                        links = dt.find_all('a', href=True)
                                                        for link in links:
                                                            href = link['href']
                                                            href_parsed = href.split(".")
                                                            if len(href_parsed) > 0:
                                                                # Get test name from link
                                                                href_test_name = href_parsed[-1]
                                                                # Compare link test name to test name from description                                                             
                                                                if href_test_name == test_desc_name:
                                                                    test_permalink = url + href
                                                                    return f"[{test_name}]({test_permalink})"
                                        except Exception as e:
                                            print(f"Error with URL {url}: {e}")

                                    # Main asynchronous function to handle all URLs concurrently
                                    async def main():
                                        async with aiohttp.ClientSession() as session:
                                            tasks = [fetch_and_process(url, session) for url in url_links]
                                            results = await asyncio.gather(*tasks)
                                            return [result for result in results if result]

                                    # Run the asynchronous code
                                    test_name_link = asyncio.run(main())
                                    if test_name_link:
                                        test_name_link = test_name_link[0]                    

                        # Compile the test details
                        test_details = [test_name_link, param_display]
                        test_details_final = "<br><br>".join(test_details) 
                        test_details_final = test_details_final + "\n\n" + exctype_message

                        payload.append(test_details_final)
            
        except Exception as ex:
            traceback.print_exc()
            print("Error Parsing File!")
        finally:
            os.remove(file_path)
        return payload
    
    def get_payload_parsed(self):
        num_payload = len(self.payload_raw)
        param = list(range(num_payload))
        
        payload = self.payload_raw
        payload_param = param
        return (payload, payload_param)

class PytestFailure(pytestxml_parser):
    def __init__(self, url, grabber):
        super(PytestFailure, self).__init__(url, grabber)
class PytestSkipped(pytestxml_parser):
    def __init__(self, url, grabber):
        super(PytestSkipped, self).__init__(url, grabber)
class PytestError(pytestxml_parser,):
    def __init__(self, url, grabber):
        super(PytestError, self).__init__(url, grabber)

class MatlabFailure(xmlParser):
    def __init__(self, url, grabber):
        super(MatlabFailure, self).__init__(url, grabber)
class MatlabSkipped(xmlParser):
    def __init__(self, url, grabber):
        super(MatlabSkipped, self).__init__(url, grabber)
class MatlabError(xmlParser):
    def __init__(self, url, grabber):
        super(MatlabError, self).__init__(url, grabber)

class InfoTxt(Parser):
    def __init__(self, url, grabber):
        self.regex_patterns = [
            "(BRANCH):\s(.+)$",
            "(PR_ID):\s(.+)$",
            "(TIMESTAMP):\s(.+)$",
            "(DIRECTION):\s(.+)$",
            "(Triggered\sby):\s(.+)$",
            "(COMMIT\sSHA):\s(.+)$",
            "(COMMIT_DATE):\s(.+)$",
            "-\s([^:\s]+)$",
        ]
        super(InfoTxt, self).__init__(url, grabber)
        

    def get_file_info(self):
        '''returns file name, file info, target_board, artifact_info_type'''
        if self.multilevel:
            url = urlparse(self.url)
            file_name = url.path.split('/')[-1]
            file_info = "NA"
            target_board="NA"
            artifact_info_type = "info_txt"
            return (file_name, file_info, target_board, artifact_info_type)

        raise Exception("Does not support non multilevel yet!")

    def get_payload_raw(self):
        payload = []
        try:
            file_path = self.grabber.download_file(self.url, self.file_name)
            with open(file_path, "r") as f:
                for l in f.readlines():
                    found = False
                    for p in self.regex_patterns:
                        if re.search(p,l.strip()):
                            found=True
                    if found:
                        payload.append(l.strip())
        except Exception as ex:
            traceback.print_exc()
            print("Error Parsing File!")
        finally:
            os.remove(file_path)

        return payload
    
    def get_payload_parsed(self):
        payload = list()
        payload_param = list()
        for l in self.payload_raw:
            for p in self.regex_patterns:
                x = re.search(p,l)
                if x and len(x.groups())==1:
                    payload.append("Built projects")
                    payload_param.append(x.group(1))
                elif x and len(x.groups())==2:
                    payload.append(x.group(1))
                    payload_param.append(x.group(2))
        return (payload, payload_param)
