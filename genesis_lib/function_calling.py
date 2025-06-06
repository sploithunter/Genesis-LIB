#!/usr/bin/env python3

"""
Function calling functionality for the GENESIS library.
This module provides classes and utilities for discovering, managing, and calling functions
in a distributed system.
"""

import os
import sys
import logging
import json
import asyncio
import time
import threading
import queue
import traceback
from typing import Dict, List, Any, Optional, Callable, Union

# Import the generic function client
from genesis_lib.function_client import GenericFunctionClient

# Configure logging
logger = logging.getLogger("genesis_function_calling")

class FunctionCallThread(threading.Thread):
    """Thread for executing function calls outside of DDS callbacks"""
    
    def __init__(self):
        """Initialize the function call thread"""
        super().__init__(daemon=True)
        self.request_queue = queue.Queue()
        self.response_queue = queue.Queue()
        self.running = True
        self.function_client = None
        self.available_functions = []
        self.function_discovery_complete = threading.Event()
        
    def run(self):
        """Main thread loop"""
        logger.info("===== TRACING: Function call thread started =====")
        
        # Initialize function client in this thread
        self.function_client = GenericFunctionClient()
        
        # Discover functions
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Wait for function discovery
            start_time = time.time()
            timeout = 10  # seconds
            
            # Run the discover_functions method to populate the discovered_functions
            try:
                logger.info("===== TRACING: Running discover_functions =====")
                loop.run_until_complete(self.function_client.discover_functions(timeout_seconds=timeout))
                
                # Now get the list of available functions
                self.available_functions = self.list_available_functions()
                
                if self.available_functions:
                    logger.info(f"===== TRACING: Discovered {len(self.available_functions)} functions =====")
                    for func in self.available_functions:
                        logger.info(f"===== TRACING: Function: {func['name']} =====")
                    self.function_discovery_complete.set()
                else:
                    logger.warning("===== TRACING: No functions discovered within timeout =====")
                    self.function_discovery_complete.set()  # Set the event even if no functions were discovered
            except Exception as e:
                logger.error(f"===== TRACING: Error discovering functions: {str(e)} =====")
                logger.error(traceback.format_exc())
                self.function_discovery_complete.set()  # Set the event even if there was an error
            
            # Process function call requests
            while self.running:
                try:
                    # Periodically check for new functions
                    if time.time() - start_time > 5:  # Check every 5 seconds
                        start_time = time.time()
                        try:
                            # Run discover_functions again to refresh the list
                            loop.run_until_complete(self.function_client.discover_functions(timeout_seconds=2))
                            self.available_functions = self.list_available_functions()
                            logger.info(f"===== TRACING: Updated function list, now have {len(self.available_functions)} functions =====")
                        except Exception as e:
                            logger.error(f"===== TRACING: Error refreshing functions: {str(e)} =====")
                    
                    # Get a request from the queue with a timeout
                    request = self.request_queue.get(timeout=0.1)
                    
                    # Extract request details
                    request_id = request.get("request_id")
                    function_id = request.get("function_id")
                    function_name = request.get("function_name")
                    kwargs = request.get("kwargs", {})
                    
                    logger.info(f"===== TRACING: Processing function call request: {function_name} =====")
                    
                    # Call the function
                    try:
                        start_time = time.time()
                        result = loop.run_until_complete(self.function_client.call_function(function_id, function_name, **kwargs))
                        end_time = time.time()
                        
                        logger.info(f"===== TRACING: Function {function_name} executed in {end_time - start_time:.2f} seconds =====")
                        logger.info(f"===== TRACING: Function {function_name} result: {result} =====")
                        
                        # Put the result in the response queue
                        self.response_queue.put({
                            "request_id": request_id,
                            "success": True,
                            "result": result,
                            "error": None
                        })
                    except Exception as e:
                        logger.error(f"===== TRACING: Error calling function {function_name}: {str(e)} =====")
                        logger.error(traceback.format_exc())
                        
                        # Put the error in the response queue
                        self.response_queue.put({
                            "request_id": request_id,
                            "success": False,
                            "result": None,
                            "error": str(e)
                        })
                    
                    # Mark the request as done
                    self.request_queue.task_done()
                    
                except queue.Empty:
                    # No requests in the queue, continue
                    pass
                except Exception as e:
                    logger.error(f"===== TRACING: Error in function call thread: {str(e)} =====")
                    logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"===== TRACING: Fatal error in function call thread: {str(e)} =====")
            logger.error(traceback.format_exc())
        finally:
            # Clean up
            if loop.is_running():
                loop.close()
    
    def stop(self):
        """Stop the function call thread"""
        logger.info("===== TRACING: Stopping function call thread =====")
        self.running = False
        self.join(timeout=2)
    
    def call_function(self, function_id, function_name, **kwargs):
        """
        Queue a function call request
        
        Args:
            function_id: The ID of the function to call
            function_name: The name of the function to call
            **kwargs: The arguments to pass to the function
            
        Returns:
            request_id: A unique ID for this request
        """
        # Generate a unique request ID
        request_id = f"req_{time.time()}_{function_name}"
        
        # Create the request
        request = {
            "request_id": request_id,
            "function_id": function_id,
            "function_name": function_name,
            "kwargs": kwargs
        }
        
        logger.info(f"===== TRACING: Queueing function call: {function_name} =====")
        logger.info(f"===== TRACING: Function arguments: {kwargs} =====")
        
        # Put the request in the queue
        self.request_queue.put(request)
        
        return request_id
    
    def list_available_functions(self):
        """
        Convert the discovered functions to a list of function metadata dictionaries
        
        Returns:
            List of function metadata dictionaries
        """
        if not self.function_client or not hasattr(self.function_client, 'discovered_functions'):
            return []
        
        functions = []
        for function_id, function_info in self.function_client.discovered_functions.items():
            if isinstance(function_info, dict):
                # Add the function ID to the function info
                function_info['function_id'] = function_id
                functions.append(function_info)
        
        return functions
    
    def get_available_functions(self):
        """Get the list of available functions"""
        # Wait for function discovery to complete (with a timeout)
        if not self.function_discovery_complete.wait(timeout=10):
            logger.warning("===== TRACING: Timed out waiting for function discovery to complete =====")
        
        # If we have a function client, get the latest functions
        if self.function_client:
            self.available_functions = self.list_available_functions()
            logger.info(f"===== TRACING: Retrieved {len(self.available_functions)} functions =====")
        
        return self.available_functions

class FunctionCaller:
    """
    Class for managing function discovery and calling in a distributed system.
    This class provides a high-level interface for discovering and calling functions.
    """
    
    def __init__(self):
        """Initialize the function caller"""
        self.function_thread = FunctionCallThread()
        self.function_thread.start()
        
        # Wait for the function thread to initialize
        time.sleep(1)
        
        # Log the number of discovered functions
        functions = self.function_thread.get_available_functions()
        logger.info(f"===== TRACING: FunctionCaller initialized with {len(functions)} functions =====")
    
    def get_function_schemas(self):
        """
        Get the schemas for all available functions
        
        Returns:
            List of function schemas
        """
        # Get the latest available functions from the function thread
        available_functions = self.function_thread.get_available_functions()
        
        logger.info(f"===== TRACING: Retrieved {len(available_functions)} function schemas =====")
        
        return available_functions
    
    def call_function(self, function_name, **kwargs):
        """
        Call a function by name
        
        Args:
            function_name: The name of the function to call
            **kwargs: The arguments to pass to the function
            
        Returns:
            The result of the function call
        """
        logger.info(f"===== TRACING: Looking up function: {function_name} =====")
        
        # Find the function by name
        available_functions = self.function_thread.get_available_functions()
        function = None
        
        for func in available_functions:
            if func["name"] == function_name:
                function = func
                break
        
        if not function:
            error_msg = f"Function {function_name} not found"
            logger.error(f"===== TRACING: {error_msg} =====")
            return {
                "success": False,
                "error": error_msg
            }
        
        # Log the function details
        function_id = function.get("function_id")
        provider_id = function.get("provider_id")
        logger.info(f"===== TRACING: Found function {function_name} with ID {function_id} from provider {provider_id} =====")
        
        # Call the function
        try:
            # Start timing the function call
            start_time = time.time()
            
            # Queue the function call
            request_id = self.function_thread.call_function(function_id, function_name, **kwargs)
            
            # Wait for the response with a timeout
            timeout = 30  # seconds
            end_time = start_time + timeout
            
            while time.time() < end_time:
                # Check if we have a response
                while not self.function_thread.response_queue.empty():
                    response = self.function_thread.response_queue.get()
                    
                    # Check if this is the response we're waiting for
                    if response.get("request_id") == request_id:
                        # Calculate the total time
                        total_time = time.time() - start_time
                        
                        if response.get("success"):
                            logger.info(f"===== TRACING: Function {function_name} completed in {total_time:.2f} seconds =====")
                            return {
                                "success": True,
                                "result": response.get("result")
                            }
                        else:
                            error_msg = response.get("error", "Unknown error")
                            logger.error(f"===== TRACING: Function {function_name} failed: {error_msg} =====")
                            return {
                                "success": False,
                                "error": error_msg
                            }
                
                # Sleep for a bit before checking again
                time.sleep(0.1)
            
            # If we get here, the function call timed out
            logger.error(f"===== TRACING: Function {function_name} timed out after {timeout} seconds =====")
            return {
                "success": False,
                "error": f"Function call timed out after {timeout} seconds"
            }
        except Exception as e:
            logger.error(f"===== TRACING: Error calling function {function_name}: {str(e)} =====")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": str(e)
            }
    
    def close(self):
        """Clean up resources"""
        logger.info("===== TRACING: Closing FunctionCaller =====")
        if self.function_thread:
            self.function_thread.stop() 