#!/usr/bin/env python3
"""
Post-installation fix for quantpylib bars import issue.
Run this script after installing quantpylib in a new virtual environment.
"""

import os
import sys
from pathlib import Path

def fix_quantpylib_feed():
    """Fix the bars import issue in quantpylib feed.py"""
    
    # Find the quantpylib installation path
    try:
        import quantpylib
        quantpylib_path = Path(quantpylib.__file__).parent
        feed_file = quantpylib_path / "hft" / "feed.py"
        
        if not feed_file.exists():
            print(f"❌ Could not find feed.py at: {feed_file}")
            return False
            
        print(f"📁 Found quantpylib at: {quantpylib_path}")
        print(f"🔧 Fixing file: {feed_file}")
        
        # Read the current content
        with open(feed_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if already fixed
        if 'bar_cls=None,' in content:
            print("✅ File already fixed!")
            return True
            
        # Apply the fix
        original_line = 'bar_cls=bars.TimeBars,'
        fixed_line = 'bar_cls=None,'
        
        if original_line in content:
            content = content.replace(original_line, fixed_line)
            
            # Write back the fixed content
            with open(feed_file, 'w', encoding='utf-8') as f:
                f.write(content)
                
            print("✅ Successfully fixed quantpylib bars import issue!")
            print(f"   Changed: {original_line}")
            print(f"   To:      {fixed_line}")
            return True
        else:
            print(f"⚠️  Could not find expected line: {original_line}")
            print("   The quantpylib version might have changed.")
            return False
            
    except ImportError:
        print("❌ quantpylib not found. Please install it first:")
        print("   pip install git+https://github.com/sumitabh1710/quantpylib.git")
        return False
    except Exception as e:
        print(f"❌ Error fixing quantpylib: {e}")
        return False

def main():
    print("🔧 Paradex Bot - quantpylib Fix Script")
    print("=" * 50)
    
    success = fix_quantpylib_feed()
    
    if success:
        print("\n🎉 Fix applied successfully!")
        print("   You can now run the bot without import errors.")
    else:
        print("\n💥 Fix failed!")
        print("   You may need to apply the fix manually.")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
