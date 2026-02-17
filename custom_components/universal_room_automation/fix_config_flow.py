#!/usr/bin/env python3
"""
Script to fix OptionsFlow methods in config_flow.py for v3.2.1.1

Run this in the v3.2.1.1 directory after copying config_flow.py from v3.2.0.10
"""
import re
import sys

def fix_options_flow_method(content: str, method_name: str) -> str:
    """Fix a single OptionsFlow method to use async_update_entry."""
    
    # Pattern: return self.async_create_entry(title="", data={...})
    # This pattern appears in OptionsFlow methods
    
    # Find the method
    method_pattern = rf'(async def {method_name}\(self.*?\):.*?)(return self\.async_create_entry\(\s*title="",\s*data=\{{[^}}]*\**self\._config_entry\.options[^}}]*\}}\s*\))'
    
    def replace_method(match):
        before = match.group(1)
        
        # Extract the data dict content
        data_dict_match = re.search(r'data=(\{.*?\})', match.group(2), re.DOTALL)
        if data_dict_match:
            data_dict = data_dict_match.group(1)
            options_dict = data_dict.replace('data=', 'options=')
            
            # Create the fixed version
            fixed = (
                f'{before}'
                f'# Update entry.options (preserves entry.data)\n        '
                f'self.hass.config_entries.async_update_entry(\n            '
                f'self._config_entry,\n            '
                f'{options_dict}\n        '
                f')\n        '
                f'return self.async_create_entry(title="", data={{}})'
            )
            return fixed
        return match.group(0)
    
    content = re.sub(method_pattern, replace_method, content, flags=re.DOTALL)
    return content

def main():
    input_file = 'config_flow.py'
    output_file = 'config_flow_fixed.py'
    
    print("Reading config_flow.py...")
    try:
        with open(input_file, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"ERROR: {input_file} not found!")
        print("Please copy config_flow.py from v3.2.0.10 first")
        sys.exit(1)
    
    print("Applying fixes to OptionsFlow methods...")
    
    methods_to_fix = [
        'async_step_automation_behavior',
        'async_step_climate',
        'async_step_covers',
        'async_step_notifications',
        'async_step_occupancy',
        'async_step_devices',
        'async_step_global_sensors',
        'async_step_energy_sensors',
        'async_step_person_tracking',
        'async_step_default_notifications',
    ]
    
    for method in methods_to_fix:
        print(f"  Fixing {method}...")
        content = fix_options_flow_method(content, method)
    
    print(f"Writing fixed version to {output_file}...")
    with open(output_file, 'w') as f:
        f.write(content)
    
    print("✅ DONE! config_flow_fixed.py created")
    print("\nNext steps:")
    print("1. Review config_flow_fixed.py")
    print("2. If looks good: mv config_flow_fixed.py config_flow.py")
    print("3. Run syntax check: python3 -m py_compile config_flow.py")

if __name__ == '__main__':
    main()
